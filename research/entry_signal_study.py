"""Estudo dos sinais de entrada candidatos (A a E) e do modelo sombra F. Protocolo: docs/entry_signals.md (fixado antes).

Entrypoint (CLAUDE.md §1): lê a base point-in-time `continuidade-v1` e o Fear & Greed, chama as funções puras de
`entry_signals`, `entry_model` e `entry_study` e grava Parquet.

    uv run python research/entry_signal_study.py

Saídas em `evidence/entry_signals/`: estatística por combinação e horizonte (execução principal e sensibilidade),
níveis por combinação, dobras do modelo, comparação F × A_90 e contagem de eventos; uma linha no registro
`evidence/validation_registry.parquet`. O teste final é avaliado uma vez, só para as combinações VALIDADO/PROMISSOR.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.signal_evidence_study import EVIDENCE_DIR, REGISTRY_PATH, git_state, load_candles  # noqa: E402
from src import config  # noqa: E402
from src.loaders.experiment_log import NEW, append_experiment  # noqa: E402
from src.loaders.market_store import read_fng  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.entry_model import (  # noqa: E402
    L2_LAMBDA,
    PURGE_DAYS,
    model_features,
    outperform_target,
    probability_frame,
    stack_rows,
    walk_forward,
)
from src.transformers.entry_signals import (  # noqa: E402
    EXECUTION_CLOSE,
    EXECUTION_OPEN,
    KIND_CROSS,
    Condition,
    EntryRules,
    build_panel,
    combos,
    conditions,
    entries,
    event_counts,
    forward_returns,
    ranking_condition,
    selection_scores,
    universe_reference,
)
from src.transformers.entry_study import (  # noqa: E402
    DEV,
    FINAL,
    LEVEL_NO_EVIDENCE,
    LEVEL_PROMISING,
    LEVEL_VALIDATED,
    ComboSpec,
    apply_holm,
    dev_level,
    levels,
    paired_difference,
    signal_table,
    stats_rows,
)
from src.transformers.policy_evaluation import data_fingerprint, experiment_id, results_digest  # noqa: E402
from src.transformers.signal_validation import ValidationRules, stable_seed  # noqa: E402

OUT_DIR = EVIDENCE_DIR / "entry_signals"
STATS_PATH = OUT_DIR / "entry_signal_stats.parquet"
LEVELS_PATH = OUT_DIR / "entry_signal_levels.parquet"
FOLDS_PATH = OUT_DIR / "entry_model_folds.parquet"
COMPARISON_PATH = OUT_DIR / "entry_model_comparison.parquet"
COUNTS_PATH = OUT_DIR / "entry_event_counts.parquet"
CLASSIFIER = f"entry-signals-v1+{config.CONTINUITY_VERSION}"
MODEL_YEARS = (2020, 2021, 2022, 2023, 2024, 2025, 2026)
MODEL_START = pd.Timestamp("2020-01-01", tz="UTC")
REFERENCE_COMBO = "A_90"
LIMITATIONS = (
    "Critério de contradição no teste final (>= 20 sinais e excesso negativo) quase nunca dispara; teste final já "
    "consultado por estudos da SMA 200; A, D, E e F se sobrepõem (momentum); horizonte fixo sem stop; pares renomeados "
    "são distintos; poucos ciclos de mercado; PROMISSOR entre 12 combinações pode ser só a melhor de várias."
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rules = ValidationRules()
    entry_rules = EntryRules()
    candles = load_candles(continuity=True)
    fingerprint = data_fingerprint(candles)
    panel = build_panel(candles, entry_rules)
    conds: dict[str, Condition] = conditions(panel, entry_rules, selection_scores(candles, panel.member))

    fng_raw = read_fng()
    fng = fng_raw.set_index("timestamp")["fng_value"].astype("float64") if not fng_raw.empty else None
    rows = stack_rows(model_features(panel, fng), outperform_target(panel, entry_rules.regime_symbol), panel.member)
    prob, folds = walk_forward(rows, MODEL_YEARS)
    conds["F"] = ranking_condition(probability_frame(prob, pd.DatetimeIndex(panel.close.index), panel.close.columns), panel.member,
                                   entry_rules.top_k)

    specs = {c.combo_id: ComboSpec(c.combo_id, c.candidate, c.kind) for c in combos(entry_rules)}
    specs["F"] = ComboSpec("F", "F", KIND_CROSS)
    events = {k: entries(conds[k].active) for k in specs}

    def tables(execution: str, period: str) -> dict[tuple[str, int], pd.DataFrame]:
        out = {}
        for h in rules.horizons:
            fwd = forward_returns(panel, h, execution)
            ref = universe_reference(fwd, panel.member)
            for combo, spec in specs.items():
                out[(combo, h)] = signal_table(events[combo], conds[combo].calculable, fwd, ref, spec.kind, h, period,
                                               rules)
        return out

    dev_tables = tables(EXECUTION_OPEN, DEV)
    main_stats = apply_holm(stats_rows(dev_tables, specs, EXECUTION_OPEN, rules))
    sens_stats = stats_rows(tables(EXECUTION_CLOSE, DEV), specs, EXECUTION_CLOSE, rules)  # fora do Holm

    # Teste final: avaliado uma vez, só para quem é VALIDADO ou PROMISSOR no desenvolvimento.
    assess = []
    for combo, group in main_stats.groupby("combo", sort=False):
        per_h = {int(r["horizon"]): r for _, r in group.iterrows()}
        if dev_level(per_h, rules.alpha)[0] in (LEVEL_VALIDATED, LEVEL_PROMISING):
            assess.append(str(combo))
    holdout: dict[tuple[str, int], tuple[int, float]] = {}
    if assess:
        final_tables = tables(EXECUTION_OPEN, FINAL)
        for combo in assess:
            for h in rules.horizons:
                t = final_tables[(combo, h)]
                holdout[(combo, h)] = (len(t), float(t["excess"].mean()) if len(t) else float("nan"))
    level_frame = levels(main_stats, holdout, rules.horizons, rules.alpha)
    for (combo, h), (n, ex) in holdout.items():
        mask = main_stats["combo"].eq(combo) & main_stats["horizon"].eq(h)
        main_stats.loc[mask, "holdout_n"] = n
        main_stats.loc[mask, "holdout_excess"] = ex

    # F só vira candidato se superar A_90 em 30 dias (IC pareado > 0) e tiver nível PROMISSOR ou VALIDADO.
    sig_f = dev_tables[("F", 30)]
    sig_a = dev_tables[(REFERENCE_COMBO, 30)]
    sig_a = sig_a[sig_a["day"].ge(MODEL_START)]
    diff = paired_difference(sig_f, sig_a, MODEL_START, stable_seed(rules.seed, "ENTRY", "F-vs-A_90", 30),
                             rules.resamples)
    f_level = str(level_frame.loc[level_frame["combo"].eq("F"), "level"].iloc[0])
    f_candidate = bool(diff.ci_low > 0 and f_level in (LEVEL_VALIDATED, LEVEL_PROMISING))
    comparison = pd.DataFrame([{
        "reference": REFERENCE_COMBO, "horizon": 30, "n_f": diff.n_f, "n_reference": diff.n_a,
        "n_clusters": diff.n_clusters, "difference": diff.difference, "ci_low": diff.ci_low, "ci_high": diff.ci_high,
        "f_level": f_level, "f_candidate": f_candidate,
    }]).astype({"reference": "string", "f_level": "string"})

    counts = event_counts(events)
    stats_all = pd.concat([main_stats, sens_stats], ignore_index=True)

    cfg = {"protocol": "docs/entry_signals.md", "horizons": list(rules.horizons), "development_end": rules.development_end,
           "holdout_start": rules.holdout_start, "alpha": rules.alpha, "seed": rules.seed, "resamples": rules.resamples,
           "cluster_days": 30, "top_k": entry_rules.top_k, "combos": list(specs), "model_years": list(MODEL_YEARS),
           "l2_lambda": L2_LAMBDA, "purge_days": PURGE_DAYS, "classifier": CLASSIFIER}
    exp_id = experiment_id(cfg, fingerprint)
    head, dirty = git_state()
    n_validated = int(level_frame["level"].eq(LEVEL_VALIDATED).sum())
    record: dict[str, object] = {
        "experiment_id": exp_id, "created_at": pd.Timestamp.now(tz="UTC"), "code_version": head, "working_tree_dirty": dirty,
        "data_fingerprint": fingerprint, "classifier_version": CLASSIFIER, "classifier_params_hash": experiment_id(cfg, "-")[:16],
        "policy_version": "comprar-por-sinal-v1", "universe": "PIT_USDT",
        "period_start": pd.Timestamp(candles["timestamp"].min()), "period_end": pd.Timestamp(candles["timestamp"].max()),
        "seed": rules.seed, "bootstrap_block": 30, "bootstrap_resamples": rules.resamples,
        "n_policies": len(specs), "n_variants": len(specs) * len(rules.horizons), "n_hypotheses": len(main_stats),
        "config_json": str(cfg),
        "results_digest": results_digest(level_frame.select_dtypes("number")),
        "results_file": str(LEVELS_PATH),
        "status": "VALIDADO" if n_validated else "NENHUM_VALIDADO",
        "limitations": LIMITATIONS,
    }
    outcome = append_experiment(record, REGISTRY_PATH)
    write_parquet(stats_all, STATS_PATH)
    write_parquet(level_frame, LEVELS_PATH)
    write_parquet(folds, FOLDS_PATH)
    write_parquet(comparison, COMPARISON_PATH)
    write_parquet(counts, COUNTS_PATH)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(f"experimento {exp_id} ({'novo' if outcome == NEW else outcome}) · dados {fingerprint[:12]} · código {head[:10]}"
          f"{' (árvore com alterações)' if dirty else ''}")
    cols = ["combo", "execution", "horizon", "n_signals", "n_coins", "n_clusters", "excess", "ci_low", "ci_high",
            "p_value", "p_holm", "stable_halves", "median_excess", "share_coins_positive", "holdout_n", "holdout_excess"]
    print(stats_all[cols].round(4).to_string(index=False))
    print(level_frame[["combo", "level", "dev_level", "holdout", "reason"]].to_string(index=False))
    print(folds.to_string(index=False))
    print(comparison.round(4).to_string(index=False))
    print("hipóteses no Holm:", len(main_stats), "· validados:", n_validated,
          "· promissores:", int(level_frame["level"].eq(LEVEL_PROMISING).sum()),
          "· sem evidência:", int(level_frame["level"].eq(LEVEL_NO_EVIDENCE).sum()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
