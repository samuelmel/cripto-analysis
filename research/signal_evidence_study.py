"""Validação estatística do sinal COMPRAR por moeda. Regras: docs/signal_validation.md (fixadas antes dos resultados).

Entrypoint (CLAUDE.md §1): lê a base point-in-time, chama as funções puras de `signal_validation` e grava Parquet.

    uv run python research/signal_evidence_study.py counts
        Só CONTAGENS de sinais independentes por moeda e horizonte. Não calcula nenhuma estatística de retorno:
        serve para fixar `config.VALIDATION_MIN_INDEPENDENT` (N_MIN) antes do estudo.

    uv run python research/signal_evidence_study.py run [--allow-second-holdout]
        Estudo completo: desenvolvimento (até config.DEVELOPMENT_END), Holm, status e teste final (hold-out, só revoga).
        Exige N_MIN em config.py. O teste final é avaliado UMA vez; uma segunda avaliação com regras diferentes exige
        `--allow-second-holdout` e fica registrada.

Base de entrada: `data/market/pit/` (montada por `research/build_pit_database.py`). Saídas (versionadas, lidas pelo
pipeline diário): `evidence/signal_evidence.parquet`, `evidence/signal_evidence_detail.parquet` e o registro append-only
`evidence/validation_registry.parquet`; cópia do primeiro em `frontend/public/signal_evidence.parquet`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.loaders.experiment_log import NEW, append_experiment  # noqa: E402
from src.loaders.market_store import read_ohlcv  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.backtest_engine import ENGINE_VERSION  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.policy_evaluation import data_fingerprint, experiment_id, results_digest  # noqa: E402
from src.transformers.signal_validation import (  # noqa: E402
    STATUS_VALIDATED,
    ValidationRules,
    apply_holdout,
    count_independent,
    evaluate_development,
    prepare,
)

PIT_DIR = Path("data/market/pit")
EVIDENCE_DIR = Path("evidence")
EVIDENCE_PATH = EVIDENCE_DIR / "signal_evidence.parquet"
DETAIL_PATH = EVIDENCE_DIR / "signal_evidence_detail.parquet"
COUNTS_PATH = EVIDENCE_DIR / "independent_counts.parquet"
REGISTRY_PATH = EVIDENCE_DIR / "validation_registry.parquet"
FRONTEND_COPY = Path("frontend/public/signal_evidence.parquet")
STATUS_HOLDOUT_DONE = "TESTE_FINAL_AVALIADO"
CLASSIFIER = "sma200+btc-regime:v1"
LIMITATIONS = (
    "Pares renomeados/migrados são símbolos distintos; sem data nem motivo oficial de deslistagem (último candle); "
    "avalia retorno em horizonte fixo, sem stop; moeda deslistada sai ao último preço; spread e slippage estimados; "
    "referência aleatória inclui a deriva de alta da própria moeda; poucos sinais independentes por moeda."
)


def git_state() -> tuple[str, bool]:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip())
        return head, dirty
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido", True


def load_candles() -> pd.DataFrame:
    folders = sorted((PIT_DIR / "ohlcv_1d").glob("symbol=*"))
    symbols = [f.name[len("symbol="):].replace("_", "/") for f in folders]
    raw = read_ohlcv(symbols, PIT_DIR)
    if raw.empty or config.REGIME_SYMBOL not in set(raw["symbol"]):
        raise SystemExit("base point-in-time ausente ou sem BTC: rode research/build_pit_database.py antes")
    return clean_candles(raw)


def cmd_counts() -> int:
    candles = load_candles()
    counts = count_independent(prepare(candles, ValidationRules()), ValidationRules())
    write_parquet(counts.astype({"symbol": "string"}), COUNTS_PATH)
    dev = counts[counts["period"].eq("DESENVOLVIMENTO")]
    print(f"{counts['symbol'].nunique()} pares na base, {dev.loc[dev['n_events'].gt(0), 'symbol'].nunique()} com algum sinal · dados até {candles['timestamp'].max():%Y-%m-%d}")
    for h in config.VALIDATION_HORIZONS:
        d = dev[dev["horizon"].eq(h)]["n_independent"]
        row = {f">={k}": int((d >= k).sum()) for k in (1, 3, 5, 8, 10, 12, 15, 20, 25, 30, 40)}
        print(f"horizonte {h} dias, moedas com sinais independentes no desenvolvimento: {row}")
    hold = counts[counts["period"].eq("TESTE_FINAL")]
    for h in config.VALIDATION_HORIZONS:
        d = hold[hold["horizon"].eq(h)]["n_independent"]
        print(f"horizonte {h} dias, teste final: " + str({f">={k}": int((d >= k).sum()) for k in (1, 3, 5, 8, 10)}))
    print(f"contagens por moeda: {COUNTS_PATH}")
    return 0


def cmd_run(allow_second: bool) -> int:
    n_min = int(getattr(config, "VALIDATION_MIN_INDEPENDENT", 0))
    if n_min < 1:
        print("config.VALIDATION_MIN_INDEPENDENT (N_MIN) ainda não foi fixado: rode `counts` e fixe-o antes")
        return 1
    rules = ValidationRules()
    candles = load_candles()
    fingerprint = data_fingerprint(candles)
    cfg = {
        "horizons": list(rules.horizons), "development_end": rules.development_end, "holdout_start": rules.holdout_start,
        "alpha": rules.alpha, "seed": rules.seed, "null_draws": rules.null_draws, "resamples": rules.resamples,
        "n_min": n_min, "holdout_min_signals": rules.holdout_min_signals, "engine": ENGINE_VERSION,
        "classifier": CLASSIFIER, "pit": repr(rules.pit),
    }
    exp_id = experiment_id(cfg, fingerprint)
    registry = pd.read_parquet(REGISTRY_PATH) if REGISTRY_PATH.is_file() else pd.DataFrame()
    done = registry[registry["status"].eq(STATUS_HOLDOUT_DONE) & registry["experiment_id"].ne(exp_id)] if not registry.empty else registry
    if not done.empty and not allow_second:
        print(f"o teste final já foi avaliado por outro experimento ({done['experiment_id'].iloc[0]}); "
              "uma segunda avaliação exige --allow-second-holdout e fica registrada")
        return 1

    prep = prepare(candles, rules)
    detail_dev, summary = evaluate_development(prep, rules, n_min)
    final, detail_hold = apply_holdout(summary, prep, rules)
    detail = pd.concat([detail_dev, detail_hold], ignore_index=True)

    candidates = int(detail_dev["n_independent"].ge(1).sum())
    tested = int(detail_dev["in_family"].sum())
    head, dirty = git_state()
    record: dict[str, object] = {
        "experiment_id": exp_id, "created_at": pd.Timestamp.now(tz="UTC"), "code_version": head, "working_tree_dirty": dirty,
        "data_fingerprint": fingerprint, "classifier_version": CLASSIFIER, "classifier_params_hash": experiment_id(cfg, "-")[:16],
        "policy_version": "comprar-sma200-v1", "universe": "PIT_USDT",
        "period_start": pd.Timestamp(candles["timestamp"].min()), "period_end": pd.Timestamp(candles["timestamp"].max()),
        "seed": rules.seed, "bootstrap_block": 0, "bootstrap_resamples": rules.resamples,
        "n_policies": int(final["symbol"].nunique()), "n_variants": len(rules.horizons),
        "n_hypotheses": tested,  # combinações (moeda, horizonte) efetivamente testadas (família do Holm)
        "config_json": str(cfg) + f" | candidatas={candidates}",
        "results_digest": results_digest(detail.drop(columns=["symbol"]).assign(symbol=detail["symbol"].astype(str)).select_dtypes("number")),
        "results_file": str(EVIDENCE_PATH), "status": STATUS_HOLDOUT_DONE, "limitations": LIMITATIONS,
    }
    outcome = append_experiment(record, REGISTRY_PATH)
    write_parquet(final, EVIDENCE_PATH)
    write_parquet(detail, DETAIL_PATH)
    write_parquet(final, FRONTEND_COPY)

    print(f"experimento {exp_id} ({'novo' if outcome == NEW else outcome}) · dados {fingerprint[:12]} · código {head[:10]}"
          f"{' (árvore com alterações)' if dirty else ''} · N_MIN {n_min}")
    print(f"combinações candidatas (moeda×horizonte com >=1 sinal): {candidates} · testadas (família de Holm): {tested}")
    print(final["status"].value_counts().to_string())
    shown = final[final["status"].ne("SEM_EVIDENCIA")].sort_values(["status", "symbol"])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(shown.drop(columns=["reason"]).round(4).to_string(index=False))
    print("validadas:", ", ".join(final.loc[final["status"].eq(STATUS_VALIDATED), "symbol"]) or "nenhuma")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("counts")
    run = sub.add_parser("run")
    run.add_argument("--allow-second-holdout", action="store_true")
    args = parser.parse_args()
    return cmd_counts() if args.cmd == "counts" else cmd_run(bool(args.allow_second_holdout))


if __name__ == "__main__":
    raise SystemExit(main())
