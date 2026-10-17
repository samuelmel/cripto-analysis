"""A regra SMA 200 reduz queda máxima e volatilidade contra comprar e segurar? Protocolo: docs/sma200_risk.md (fixado antes).

Entrypoint (CLAUDE.md §1): lê a base point-in-time com a correção de continuidade, chama as funções puras de `risk_study`
e grava Parquet em `evidence/continuidade_v1/`.

    uv run python research/risk_sma200_study.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.signal_evidence_study import CONTINUITY_DIR, REGISTRY_PATH, git_state, load_candles  # noqa: E402
from src import config  # noqa: E402
from src.loaders.experiment_log import NEW, append_experiment  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.policy_evaluation import data_fingerprint, experiment_id, results_digest  # noqa: E402
from src.transformers.risk_study import (  # noqa: E402
    BLOCK_DAYS,
    MIN_DAYS,
    PERIOD_DEV,
    coin_paths,
    coin_table,
    confirm_on_test,
    evaluate_risk,
)
from src.transformers.signal_validation import ValidationRules, prepare  # noqa: E402

CLASSIFIER = f"sma200-risk:v1+{config.CONTINUITY_VERSION}"
LIMITATIONS = (
    "Poucos ciclos de mercado; bootstrap em blocos de 60 dias distorce o nível absoluto da queda máxima (o IC é da diferença "
    "pareada); queda máxima de ativo isolado não é risco de carteira; referência é comprar e segurar a mesma moeda; "
    "reduzir risco ficando em caixa também reduz o ganho."
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rules = ValidationRules()
    candles = load_candles(True)
    fingerprint = data_fingerprint(candles)
    prep = prepare(candles, rules)
    summary, table = evaluate_risk(prep, rules)
    final = confirm_on_test(summary, prep, rules)
    test_table = coin_table(coin_paths(prep, "TESTE_FINAL", rules)) if final["test_n_coins"].notna().any() else pd.DataFrame()

    cfg = {"alpha": rules.alpha, "seed": rules.seed, "resamples": rules.resamples, "block_days": BLOCK_DAYS,
           "min_days": MIN_DAYS, "development_end": rules.development_end, "classifier": CLASSIFIER}
    exp_id = experiment_id(cfg, fingerprint)
    head, dirty = git_state()
    record: dict[str, object] = {
        "experiment_id": exp_id, "created_at": pd.Timestamp.now(tz="UTC"), "code_version": head, "working_tree_dirty": dirty,
        "data_fingerprint": fingerprint, "classifier_version": CLASSIFIER, "classifier_params_hash": experiment_id(cfg, "-")[:16],
        "policy_version": "sma200-vs-buy-and-hold-v1", "universe": "PIT_USDT",
        "period_start": pd.Timestamp(candles["timestamp"].min()), "period_end": pd.Timestamp(candles["timestamp"].max()),
        "seed": rules.seed, "bootstrap_block": BLOCK_DAYS, "bootstrap_resamples": rules.resamples,
        "n_policies": int(len(table)), "n_variants": 2, "n_hypotheses": 2, "config_json": str(cfg),
        "results_digest": results_digest(final.select_dtypes("number")),
        "results_file": str(CONTINUITY_DIR / "risk_sma200.parquet"), "status": str(final["status"].iloc[0]),
        "limitations": LIMITATIONS,
    }
    outcome = append_experiment(record, REGISTRY_PATH)
    write_parquet(final.assign(metric=final["metric"].astype("string"), status=final["status"].astype("string")),
                  CONTINUITY_DIR / "risk_sma200.parquet")
    write_parquet(table, CONTINUITY_DIR / "risk_sma200_by_coin.parquet")
    if not test_table.empty:
        write_parquet(test_table, CONTINUITY_DIR / "risk_sma200_by_coin_test.parquet")

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(f"experimento {exp_id} ({'novo' if outcome == NEW else outcome}) · dados {fingerprint[:12]} · código {head[:10]}"
          f"{' (árvore com alterações)' if dirty else ''} · {PERIOD_DEV}")
    print(final.round(4).T.to_string())
    pairs = table[table["symbol"].isin(["BTC/USDT", "ETH/USDT"])]
    print(pairs[["symbol", "days", "exposure", "mdd_hold", "mdd_strategy", "mdd_control", "vol_hold", "vol_strategy",
                 "total_return_hold", "total_return_strategy"]].round(3).to_string(index=False))
    print("veredito:", final["status"].iloc[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
