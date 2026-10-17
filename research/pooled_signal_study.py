"""Teste agregado da regra SMA 200 (todas as moedas juntas). Protocolo: docs/pooled_validation.md (fixado antes).

Entrypoint (CLAUDE.md §1): lê a base point-in-time, chama as funções puras de `pooled_validation` e grava Parquet.

    uv run python research/pooled_signal_study.py

Saídas: `evidence/pooled_signal_evidence.parquet` (veredito por horizonte), `evidence/pooled_signal_sensitivity.parquet`
(descritivo) e uma linha no registro `evidence/validation_registry.parquet`. Não altera o COMPRAR de nenhuma moeda.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.signal_evidence_study import (  # noqa: E402
    EVIDENCE_DIR,
    REGISTRY_PATH,
    git_state,
    load_candles,
)
from src.loaders.experiment_log import NEW, append_experiment  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.policy_evaluation import data_fingerprint, experiment_id, results_digest  # noqa: E402
from src.transformers.pooled_validation import (  # noqa: E402
    apply_pooled_holdout,
    evaluate_pooled,
    pooled_signals,
    pooled_stats,
    sensitivity,
    top_by_signals,
)
from src.transformers.signal_validation import ValidationRules, prepare, stable_seed  # noqa: E402

RESULT_PATH = EVIDENCE_DIR / "pooled_signal_evidence.parquet"
SENSITIVITY_PATH = EVIDENCE_DIR / "pooled_signal_sensitivity.parquet"
CLASSIFIER = "sma200+btc-regime:pooled-v1"
LIMITATIONS = (
    "Segunda olhada nos mesmos dados de desenvolvimento, motivada pelo resultado nulo por moeda; pares renomeados são "
    "distintos; retorno em horizonte fixo sem stop; referência inclui a deriva da própria moeda; poucos ciclos de mercado; "
    "vale para a média do conjunto, não para cada moeda."
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rules = ValidationRules()
    candles = load_candles()
    fingerprint = data_fingerprint(candles)
    prep = prepare(candles, rules)
    final = apply_pooled_holdout(evaluate_pooled(prep, rules), prep, rules)

    rows = []
    for h in rules.horizons:
        sig = pooled_signals(prep, h, "DESENVOLVIMENTO", rules)
        seed = stable_seed(rules.seed, "POOLED", h)
        variants = {"TODAS": set(), "SEM_BTC_ETH": {"BTC/USDT", "ETH/USDT"}, "SEM_5_MAIS_FREQUENTES": top_by_signals(sig, 5)}
        for name, excluded in variants.items():
            s = sensitivity(sig, excluded, seed, rules.resamples) if excluded else pooled_stats(sig, seed, rules.resamples)
            rows.append({"horizon": h, "variant": name, "n_signals": s.n_signals, "n_coins": s.n_coins,
                         "excess": s.excess, "ci_low": s.ci_low, "ci_high": s.ci_high, "p_value": s.p_value,
                         "coin_weighted_excess": s.coin_weighted_excess, "median_excess": s.median_excess})
    sens = pd.DataFrame(rows).astype({"variant": "string"})

    cfg = {"horizons": list(rules.horizons), "development_end": rules.development_end, "alpha": rules.alpha,
           "seed": rules.seed, "resamples": rules.resamples, "cluster_days": 30, "classifier": CLASSIFIER}
    exp_id = experiment_id(cfg, fingerprint)
    head, dirty = git_state()
    record: dict[str, object] = {
        "experiment_id": exp_id, "created_at": pd.Timestamp.now(tz="UTC"), "code_version": head, "working_tree_dirty": dirty,
        "data_fingerprint": fingerprint, "classifier_version": CLASSIFIER, "classifier_params_hash": experiment_id(cfg, "-")[:16],
        "policy_version": "comprar-sma200-v1", "universe": "PIT_USDT",
        "period_start": pd.Timestamp(candles["timestamp"].min()), "period_end": pd.Timestamp(candles["timestamp"].max()),
        "seed": rules.seed, "bootstrap_block": 30, "bootstrap_resamples": rules.resamples,
        "n_policies": 1, "n_variants": len(rules.horizons), "n_hypotheses": len(rules.horizons),
        "config_json": str(cfg),
        "results_digest": results_digest(final.select_dtypes("number")),
        "results_file": str(RESULT_PATH), "status": str(final["status"].iloc[0]), "limitations": LIMITATIONS,
    }
    outcome = append_experiment(record, REGISTRY_PATH)
    write_parquet(final.assign(status=final["status"].astype("string")), RESULT_PATH)
    write_parquet(sens, SENSITIVITY_PATH)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"experimento {exp_id} ({'novo' if outcome == NEW else outcome}) · dados {fingerprint[:12]} · código {head[:10]}"
          f"{' (árvore com alterações)' if dirty else ''}")
    print(final.round(4).to_string(index=False))
    print(sens.round(4).to_string(index=False))
    print("veredito:", final["status"].iloc[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
