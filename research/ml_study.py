"""Estudo da IA (modelos em sombra contra o universo e o momento simples). Protocolo: docs/ml_study.md (fixado antes).

Entrypoint (CLAUDE.md §1): lê os candles do arquivo oficial (`data/archive`) com o filtro `continuidade-v1`, o Fear &
Greed (`data/market/fng` ou a cópia da branch state, `data/state/fng_history.parquet`), chama `ml_study.run_study` e
grava Parquet em `evidence/ml_study/`, com uma linha no registro `evidence/validation_registry.parquet`.

    uv run python research/ml_study.py
    uv run python research/ml_study.py --fng caminho/fng_history.parquet   cópia do F&G tirada da branch state
    uv run python research/ml_study.py --v2     estudo v2 EXPLORATÓRIO (docs/ml_study_v2.md): base ampliada com os pares
                                                em BTC de data/archive_btc e ranking de todas as moedas
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.signal_evidence_study import REGISTRY_PATH, git_state  # noqa: E402
from src.loaders.archive_store import read_archive_candles  # noqa: E402
from src.loaders.experiment_log import NEW, append_experiment  # noqa: E402
from src.loaders.market_store import read_fng  # noqa: E402
from src.loaders.model_log_store import read_fng_history  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.entry_model import model_features, outperform_target  # noqa: E402
from src.transformers.entry_signals import EntryRules, build_panel  # noqa: E402
from src.transformers.gbm import GBMParams  # noqa: E402
from src.transformers.ml_study import LEVEL_VALIDATED, StudyRules, ranking_study, run_study  # noqa: E402
from src.transformers.quote_conversion import splice, to_usdt  # noqa: E402
from src.transformers.model_shadow import MODELS, PROTOCOL, fng_series, latest_fng, stack_all  # noqa: E402
from src.transformers.policy_evaluation import data_fingerprint, experiment_id, results_digest  # noqa: E402
from src.transformers.series_continuity import ContinuityRules, split_discontinuities  # noqa: E402

OUT_DIR = Path("evidence/ml_study")
OUT_DIR_V2 = Path("evidence/ml_study_v2")
BTC_DIR = Path("data/archive_btc")
LIMITATIONS = (
    "histórico já explorado; uma única história de mercado; janelas de 30 dias sobrepostas (~60 observações "
    "independentes no desenvolvimento); modelos e momento se sobrepõem; deslistagem pelo último preço; renomeações como "
    "saída; spread e slippage estimados; base do arquivo oficial (S3)"
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_fng(path: Path | None) -> pd.DataFrame:
    if path is not None:
        return latest_fng(read_fng_history(path))
    fng = read_fng()
    return fng if not fng.empty else latest_fng(read_fng_history())


def main() -> int:
    parser = argparse.ArgumentParser(description="Estudo da IA (docs/ml_study.md)")
    parser.add_argument("--fng", type=Path, default=None, help="fng_history.parquet da branch state")
    parser.add_argument("--v2", action="store_true", help="estudo v2 exploratório (docs/ml_study_v2.md)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rules = StudyRules()
    log("lendo a base do arquivo e aplicando continuidade-v1")
    raw = clean_candles(read_archive_candles())
    if args.v2:
        btc_pairs = read_archive_candles(base=BTC_DIR)
        if btc_pairs.empty:
            print("data/archive_btc vazio: rode research/build_btc_pairs.py antes", file=sys.stderr)
            return 1
        converted = to_usdt(clean_candles(btc_pairs), raw[raw["symbol"].eq("BTC/USDT")])
        raw = clean_candles(splice(raw, converted))
        log(f"pares em BTC convertidos: {converted['symbol'].nunique()} moedas, {len(converted)} candles")
    candles, _ = split_discontinuities(raw, ContinuityRules())
    fng = load_fng(args.fng)
    fng_ok = not fng.empty
    log(f"{candles['symbol'].nunique()} séries, {len(candles)} candles; Fear & Greed: "
        + (f"{len(fng)} dias até {fng['timestamp'].max():%Y-%m-%d}" if fng_ok else "INDISPONÍVEL"))
    panel = build_panel(candles, EntryRules())
    rows = stack_all(model_features(panel, fng_series(fng)), outperform_target(panel, "BTC/USDT"), panel.member)
    log(f"{len(rows)} linhas (dia, moeda) no universo; walk-forward dos modelos")
    if args.v2:
        return run_v2(rows, panel, fng_ok, rules, candles)
    result = run_study(rows, panel, fng_ok, rules)

    fp = data_fingerprint(candles)
    cfg = {"protocol": "docs/ml_study.md", "version": PROTOCOL, "models": [m.name for m in MODELS],
           "versions": {m.name: m.version for m in MODELS}, "gbm": str(GBMParams()), "years": list(rules.years),
           "development_end": str(rules.development_end), "holdout_start": str(rules.holdout_start), "top_k": rules.top_k,
           "min_universe": rules.min_universe, "alpha": rules.alpha, "seed": rules.boot.seed, "resamples": rules.boot.n_boot,
           "min_block": rules.min_block, "fng_available": fng_ok}
    exp_id = experiment_id(cfg, fp)
    head, dirty = git_state()
    validated = int(result.levels["level"].eq(LEVEL_VALIDATED).sum())
    record: dict[str, object] = {
        "experiment_id": exp_id, "created_at": pd.Timestamp.now(tz="UTC"), "code_version": head, "working_tree_dirty": dirty,
        "data_fingerprint": fp, "classifier_version": PROTOCOL, "classifier_params_hash": experiment_id(cfg, "-")[:16],
        "policy_version": "ia-sombra-v1", "universe": "PIT_USDT", "period_start": pd.Timestamp(candles["timestamp"].min()),
        "period_end": pd.Timestamp(candles["timestamp"].max()), "seed": rules.boot.seed, "bootstrap_block": int(rules.min_block),
        "bootstrap_resamples": rules.boot.n_boot, "n_policies": len(MODELS), "n_variants": len(MODELS) * 2,
        "n_hypotheses": len(MODELS) * 2, "config_json": str(cfg),
        "results_digest": results_digest(result.tests.select_dtypes("number")), "results_file": str(OUT_DIR / "tests.parquet"),
        "status": "VALIDADO" if validated else "NENHUM_VALIDADO", "limitations": LIMITATIONS,
    }
    outcome = append_experiment(record, REGISTRY_PATH)
    for name in ("predictive", "calibration", "tests", "levels", "sensitivity", "folds", "daily"):
        table = getattr(result, name)
        if not table.empty:
            write_parquet(table, OUT_DIR / f"{name}.parquet")

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(f"\nexperimento {exp_id} ({'novo' if outcome == NEW else outcome}) · dados {fp[:12]} · código {head[:10]}"
          f"{' (árvore com alterações)' if dirty else ''}")
    print("\npreditivas:\n" + result.predictive.round(4).to_string(index=False))
    print("\ntestes (excesso médio em 30 dias, fração):\n" + result.tests.round(4).to_string(index=False))
    print("\nníveis:\n" + result.levels.to_string(index=False))
    if not result.sensitivity.empty:
        print("\nsensibilidade (desenvolvimento):\n" + result.sensitivity.round(4).to_string(index=False))
    return 0


def run_v2(rows: pd.DataFrame, panel: object, fng_ok: bool, rules: StudyRules, candles: pd.DataFrame) -> int:
    from src.transformers.entry_signals import Panel

    assert isinstance(panel, Panel)
    table = ranking_study(rows, panel, fng_ok, rules)
    fp = data_fingerprint(candles)
    head, dirty = git_state()
    write_parquet(table.assign(data_fingerprint=fp, code_version=head), OUT_DIR_V2 / "ranking.parquet")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(f"\nv2 EXPLORATÓRIO · dados {fp[:12]} · código {head[:10]}{' (árvore com alterações)' if dirty else ''}")
    print(f"{candles['symbol'].nunique()} séries, {len(candles)} candles, {len(rows)} linhas no universo")
    print(table.round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
