"""Fase 5 (pesquisa): políticas por regime, causalidade, custos de transição, comparabilidade dos baselines,
separação cronológica, métricas e bootstrap, registro de experimentos e isolamento da produção. Sem rede."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.loaders.experiment_log import (
    NEW,
    REGISTRY_SCHEMA,
    REPRODUCED,
    ExperimentConflict,
    append_experiment,
    read_registry,
)
from src.transformers.policy_evaluation import (
    SharpeComparison,
    block_indices,
    classify_evidence,
    chronological_split,
    data_fingerprint,
    drawdown_stats,
    effective_sample_size,
    experiment_id,
    holm_adjust,
    metrics,
    paired_sharpe_bootstrap,
    results_digest,
    sharpe_of,
    year_windows,
)
from src.transformers.policy_experiment import BASELINES, Scenario, run_scenario
from src.transformers.policy_study import POLICY_NAMES, Protocol, run_study, windows_for
from src.transformers.regime_policy import (
    ANY,
    CASH,
    FIXED_POLICIES,
    MIN_TRAIN_DAYS,
    POLICY_HOLD_UP,
    POLICY_LEARNED,
    POLICY_MOMENTUM_UP,
    POLICY_PRIMARY,
    POLICY_VOL_FILTERED,
    RegimePolicy,
    fit_mapping,
    fixed_chooser,
    learned_chooser,
    policy_targets,
    random_dropout,
)
from src.transformers.regimes import RegimeRules, classify_market_regimes
from src.transformers.selection import compute_features
from src.transformers.selection_backtest import (
    STRATEGY_BTC,
    STRATEGY_HOLD_ALL,
    STRATEGY_MOMENTUM,
    STRATEGY_SMA200,
    market_returns,
    rebalance_days,
)
from src.transformers.strategies import market_from_candles
from tests.helpers import make_candles

ROOT = Path(__file__).resolve().parent.parent
END = pd.Timestamp("2026-06-30", tz="UTC")
SEED = 7
START = pd.Timestamp("2025-01-01", tz="UTC")
ONE_DAY = pd.Timedelta(days=1)
SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "XRP/USDT")


def closes(days: int = 900, seed: int = 3) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    common = 0.012 * rng.standard_normal(days)
    out: dict[str, np.ndarray] = {}
    for i, symbol in enumerate(SYMBOLS):
        drift = 0.0030 - 0.0003 * i
        noise = 0.5 * common + 0.010 * rng.standard_normal(days)
        shock = np.where(np.arange(days) // 250 % 2 == 1, -0.0045, 0.0)  # fases de queda: sem elas o regime nunca troca
        out[symbol] = 100.0 * np.exp(np.cumsum(drift + shock + noise))
    return out


def world(days: int = 900, end: pd.Timestamp = END, seed: int = 3) -> pd.DataFrame:
    return make_candles({s: list(v) for s, v in closes(days, seed).items()}, end)


def as_of_for(end: pd.Timestamp) -> pd.Timestamp:
    return end + ONE_DAY + pd.Timedelta(minutes=10)


def setup(candles: pd.DataFrame, end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    features = compute_features(market_from_candles(candles))
    btc = candles[candles["symbol"].eq("BTC/USDT")]
    regime = classify_market_regimes(pd.Series(btc["close"].to_numpy(), index=pd.DatetimeIndex(btc["timestamp"])), as_of_for(end))
    return features, regime


@lru_cache(maxsize=1)
def full_world() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candles = world()
    features, regime = setup(candles, END)
    return candles, features, regime


def run(features: pd.DataFrame, regime: pd.DataFrame, scenario: Scenario = Scenario(), end: pd.Timestamp = END):  # type: ignore[no-untyped-def]
    return run_scenario(features, regime, scenario, START, end, SEED)


# ---------------------------------------------------------------------------------------------
# Mapeamento determinístico; MISTO e INDISPONIVEL
# ---------------------------------------------------------------------------------------------

def test_policy_tables_are_deterministic_and_never_promote_unclear_states() -> None:
    p1 = FIXED_POLICIES[POLICY_PRIMARY]
    assert p1.choose("ALTA", "NORMAL") == p1.choose("ALTA", "NORMAL") == STRATEGY_SMA200
    for state in ("MISTO", "LATERAL", "BAIXA", "INDETERMINADO", "INDISPONIVEL"):
        assert p1.choose(state, "NORMAL") == CASH
    p3 = FIXED_POLICIES[POLICY_VOL_FILTERED]
    assert p3.choose("ALTA", "NORMAL") == STRATEGY_SMA200 and p3.choose("ALTA", "ALTA") == CASH
    assert p3.choose("ALTA", "INDISPONIVEL") == CASH
    p2 = FIXED_POLICIES[POLICY_MOMENTUM_UP]
    assert (p2.choose("ALTA", "NORMAL"), p2.choose("MISTO", "ALTA"), p2.choose("BAIXA", "NORMAL")) == (STRATEGY_MOMENTUM, STRATEGY_SMA200, CASH)
    assert FIXED_POLICIES[POLICY_HOLD_UP].choose("ALTA", "ALTA") == STRATEGY_HOLD_ALL
    assert len({p.fingerprint() for p in FIXED_POLICIES.values()}) == len(FIXED_POLICIES)
    assert p1.fingerprint() == RegimePolicy(p1.name, p1.rows).fingerprint()


def test_invalid_policies_and_scenarios_are_rejected() -> None:
    for bad in (("NADA", ANY, STRATEGY_SMA200), ("ALTA", "NADA", STRATEGY_SMA200), ("ALTA", ANY, "INEXISTENTE")):
        with pytest.raises(ValueError):
            RegimePolicy("x", (bad,))
    with pytest.raises(ValueError):
        RegimePolicy("x", (), default="INEXISTENTE")
    for kwargs in (dict(cost_scale=-1.0), dict(lag_days=-1), dict(every=0), dict(regime_dropout=1.0), dict(band=-0.1)):
        with pytest.raises(ValueError):
            Scenario(**kwargs)  # type: ignore[arg-type]


def test_regime_known_after_the_decision_close_is_refused_and_missing_regime_means_cash() -> None:
    _, features, regime = full_world()
    days = [pd.Timestamp(d) for d in rebalance_days(features, 7)]
    zero = pd.DataFrame(0.0, index=pd.DatetimeIndex(days), columns=sorted(set(features.index.get_level_values("symbol"))))
    cands = {s: zero + 0.1 for s in (STRATEGY_HOLD_ALL, STRATEGY_SMA200, STRATEGY_MOMENTUM)} | {CASH: zero}
    late = regime.assign(known_at=regime["timestamp"] + pd.Timedelta(days=2))
    with pytest.raises(ValueError, match="depois do fechamento"):
        policy_targets(fixed_chooser(FIXED_POLICIES[POLICY_PRIMARY]), POLICY_PRIMARY, cands, late, days)
    empty = regime.iloc[0:0]
    weights, decisions = policy_targets(fixed_chooser(FIXED_POLICIES[POLICY_HOLD_UP]), POLICY_HOLD_UP, cands, empty, days)
    assert (weights == 0).all().all() and decisions["strategy"].eq(CASH).all() and decisions["trend_regime"].eq("INDISPONIVEL").all()


# ---------------------------------------------------------------------------------------------
# Comparabilidade dos baselines e custos de transição
# ---------------------------------------------------------------------------------------------

def test_all_policies_and_baselines_share_calendar_costs_and_exposure_limit() -> None:
    _, features, regime = full_world()
    result = run(features, regime)
    names = set(result.runs)
    assert set(POLICY_NAMES) | set(BASELINES) == names
    indexes = {n: r.daily.index for n, r in result.runs.items()}
    reference = indexes[STRATEGY_BTC]
    assert all(idx.equals(reference) for idx in indexes.values())
    assert reference.min() == START and reference.max() == END
    # Motor versão 2: a guarda de exposição impede passar de 100% mesmo com a faixa de tolerância (era possível ~118%).
    assert all(float(r.exposure.max()) <= 1.0 + 1e-9 for r in result.runs.values())
    exact = run(features, regime, Scenario(band=0.0))
    assert all(float(r.exposure.max()) <= 1.0 + 1e-9 for r in exact.runs.values())
    free = run(features, regime, Scenario(cost_scale=0.0))
    assert all(r.cost == 0.0 for r in free.runs.values())
    assert all(r.exposure.iloc[0] == 0.0 for r in result.runs.values())  # todos começam em caixa


def test_a_policy_that_never_leaves_a_strategy_matches_that_baseline_exactly() -> None:
    _, features, regime = full_world()
    always_up = regime.assign(trend_regime="ALTA", vol_regime="NORMAL")
    result = run(features, always_up)
    pd.testing.assert_series_equal(result.runs[POLICY_PRIMARY].daily, result.runs[STRATEGY_SMA200].daily)
    pd.testing.assert_series_equal(result.runs[POLICY_HOLD_UP].daily, result.runs[STRATEGY_HOLD_ALL].daily)
    pd.testing.assert_series_equal(result.runs[POLICY_MOMENTUM_UP].daily, result.runs[STRATEGY_MOMENTUM].daily)
    assert result.runs[STRATEGY_SMA200].exposure.max() > 0  # o teste não é vazio
    assert result.switches[POLICY_PRIMARY] == 0


def test_defensive_regime_keeps_the_portfolio_in_cash_without_costs() -> None:
    _, features, regime = full_world()
    result = run(features, regime.assign(trend_regime="BAIXA"))
    for name in (POLICY_PRIMARY, POLICY_MOMENTUM_UP, POLICY_VOL_FILTERED, POLICY_HOLD_UP):
        run_ = result.runs[name]
        assert (run_.daily == 0).all() and run_.cost == 0 and run_.n_trades == 0 and run_.exposure.max() == 0


def test_switching_with_an_open_position_pays_the_exit_cost_at_the_next_rebalance() -> None:
    _, features, regime = full_world()
    switch = pd.Timestamp("2025-09-01", tz="UTC")
    flipped = regime.assign(trend_regime=np.where(regime["timestamp"] < switch, "ALTA", "MISTO"))
    result = run(features, flipped)
    policy, baseline = result.runs[POLICY_PRIMARY], result.runs[STRATEGY_SMA200]
    decisions = result.decisions[result.decisions["policy"].eq(POLICY_PRIMARY)]
    first_cash = pd.Timestamp(decisions.loc[decisions["strategy"].eq(CASH) & decisions["day"].ge(switch), "day"].iloc[0])
    assert (first_cash - switch).days < 7  # a troca só vale no próximo dia de rebalanceamento
    assert baseline.exposure.loc[:first_cash].max() > 0
    pd.testing.assert_series_equal(policy.daily.loc[:first_cash], baseline.daily.loc[:first_cash])  # igual até a troca
    after = first_cash + ONE_DAY
    assert policy.daily.loc[after] < 0 and policy.exposure.loc[after] == 0.0  # só o custo de sair, e fica em caixa
    assert policy.cost > 0 and policy.turnover > 0 and result.switches[POLICY_PRIMARY] >= 1
    assert (policy.daily.loc[after + ONE_DAY:] == 0).all()
    assert policy.cost < baseline.cost + 0.5  # custo finito e contabilizado, nunca omitido


def test_ineligible_assets_and_short_history_get_no_weight_and_data_failures_go_to_cash() -> None:
    raw = closes()
    short = {s: list(v) for s, v in raw.items()}
    short["NEW/USDT"] = list(100.0 * np.exp(np.cumsum(np.full(60, 0.004))))
    candles = make_candles(short, END)
    features, regime = setup(candles, END)
    result = run(features, regime)
    assert "NEW/USDT" in result.eligible_symbols
    weights = features[features.index.get_level_values("symbol") == "NEW/USDT"]
    assert weights["sma_200"].isna().all()  # sem SMA 200 -> inelegível para HOLD_ALL/SMA200 em todo o período
    dropped = run(features, regime, Scenario(regime_dropout=0.5))
    base_cash = result.decisions[result.decisions["policy"].eq(POLICY_PRIMARY)]["strategy"].eq(CASH).mean()
    cash_share = dropped.decisions[dropped.decisions["policy"].eq(POLICY_PRIMARY)]["strategy"].eq(CASH).mean()
    assert cash_share > base_cash
    only_core = run(features, regime, Scenario(universe=("BTC/USDT", "ETH/USDT")))
    assert only_core.eligible_symbols == ("BTC/USDT", "ETH/USDT")
    assert random_dropout(regime, 0.0, 1) is regime
    a, b = random_dropout(regime, 0.3, 5), random_dropout(regime, 0.3, 5)
    pd.testing.assert_frame_equal(a, b)
    classified = regime["trend_regime"].ne("INDISPONIVEL")
    assert a.loc[classified, "trend_regime"].eq("INDISPONIVEL").mean() == pytest.approx(0.3, abs=0.08)


def test_execution_lag_delays_every_position_by_the_same_days() -> None:
    _, features, regime = full_world()
    base, lagged = run(features, regime), run(features, regime, Scenario(lag_days=1))
    assert lagged.runs[STRATEGY_BTC].daily.index.equals(base.runs[STRATEGY_BTC].daily.index)
    assert not lagged.runs[STRATEGY_SMA200].daily.equals(base.runs[STRATEGY_SMA200].daily)


# ---------------------------------------------------------------------------------------------
# Causalidade e separação treino/teste
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cut", ["2025-06-15", "2025-12-31"])
def test_decisions_and_returns_up_to_a_day_do_not_depend_on_later_data(cut: str) -> None:
    candles, features, regime = full_world()
    cut_day = pd.Timestamp(cut, tz="UTC")
    truncated = candles[candles["timestamp"] <= cut_day]
    f_cut, r_cut = setup(truncated, cut_day)
    full = run(features, regime)
    short = run_scenario(f_cut, r_cut, Scenario(), START, cut_day, SEED)
    d_full = full.decisions[full.decisions["day"] <= cut_day].reset_index(drop=True)
    d_short = short.decisions.reset_index(drop=True)
    pd.testing.assert_frame_equal(d_full, d_short)
    for name, run_ in short.runs.items():
        pd.testing.assert_series_equal(full.runs[name].daily.loc[:cut_day], run_.daily, check_freq=False)
    future = candles.copy()
    future.loc[future["timestamp"] > cut_day, "close"] *= 4.0
    f_alt, r_alt = setup(future, END)
    altered = run(f_alt, r_alt)
    for name in POLICY_NAMES + BASELINES:
        pd.testing.assert_series_equal(full.runs[name].daily.loc[:cut_day], altered.runs[name].daily.loc[:cut_day], check_freq=False)


def test_learned_mapping_uses_only_returns_before_the_training_end() -> None:
    idx = pd.date_range("2022-01-01", periods=1200, freq="D", tz="UTC")
    rng = np.random.default_rng(0)
    trend = pd.Series(np.where(np.arange(1200) % 600 < 300, "ALTA", "BAIXA"), index=idx)
    frame = pd.DataFrame({s: 0.0005 * (trend == "ALTA").to_numpy() + 0.01 * rng.standard_normal(1200) for s in
                          (STRATEGY_HOLD_ALL, STRATEGY_SMA200, STRATEGY_MOMENTUM)}, index=idx)
    train_end = pd.Timestamp("2024-01-01", tz="UTC")
    mapping, days = fit_mapping(frame, trend, train_end)
    assert days["ALTA"] >= MIN_TRAIN_DAYS and mapping["ALTA"] in frame.columns
    mutated = frame.copy()
    mutated.loc[mutated.index >= train_end] = 5.0
    assert fit_mapping(mutated, trend, train_end) == (mapping, days)  # o futuro não entra
    earlier = frame.copy()
    earlier.loc[earlier.index < train_end] = -0.05
    assert fit_mapping(earlier, trend, train_end)[0]["ALTA"] == CASH  # e o passado, sim, e Sharpe <= 0 -> caixa
    sparse = fit_mapping(frame.iloc[:100], trend, train_end)
    assert set(sparse[0].values()) == {CASH}  # amostra insuficiente -> caixa
    choose, tables = learned_chooser(frame, trend)
    assert choose(pd.Timestamp("2024-03-01", tz="UTC"), "ALTA", "NORMAL") == mapping["ALTA"]
    assert choose(pd.Timestamp("2024-03-01", tz="UTC"), "INDISPONIVEL", "NORMAL") == CASH
    assert tables()["year"].tolist() == [2024] * 4


def test_chronological_split_is_ordered_disjoint_and_complete() -> None:
    idx = pd.date_range("2018-01-01", "2026-06-30", freq="D", tz="UTC")
    split = chronological_split(idx, pd.Timestamp("2020-12-31", tz="UTC"), pd.Timestamp("2022-12-31", tz="UTC"))
    assert sum(len(v) for v in split.values()) == len(idx)
    assert split["TREINO"].max() < split["VALIDACAO"].min() and split["VALIDACAO"].max() < split["TESTE"].min()
    with pytest.raises(ValueError):
        chronological_split(idx, pd.Timestamp("2022-12-31", tz="UTC"), pd.Timestamp("2020-12-31", tz="UTC"))
    assert list(year_windows(idx)) == [str(y) for y in range(2018, 2027)]
    windows = windows_for(START, END)
    assert windows["PRIMARIA"] == (START, END) and windows["TESTE"][0] >= pd.Timestamp("2023-01-01", tz="UTC")


# ---------------------------------------------------------------------------------------------
# Métricas e incerteza
# ---------------------------------------------------------------------------------------------

def test_metrics_respect_the_minimum_sample_and_compute_drawdown_recovery() -> None:
    short = pd.Series(np.full(100, 0.001), index=pd.date_range("2025-01-01", periods=100, freq="D", tz="UTC"))
    m = metrics(short)
    assert np.isnan(m["sharpe"]) and np.isnan(m["sortino"]) and np.isnan(m["annual_return_pct"]) and m["n_days"] == 100
    assert m["total_return_pct"] == pytest.approx((1.001 ** 100 - 1) * 100)
    r = pd.Series([0.1, -0.2, -0.1, 0.05, 0.3, 0.1], index=pd.date_range("2025-01-01", periods=6, freq="D", tz="UTC"))
    dd, recovery, longest = drawdown_stats(r)
    assert dd == pytest.approx(-28.0) and recovery == 3 and longest == 4  # submerso nos dias 2 a 5
    never = pd.Series([0.1, -0.5, 0.0], index=pd.date_range("2025-01-01", periods=3, freq="D", tz="UTC"))
    assert np.isnan(drawdown_stats(never)[1])
    rng = np.random.default_rng(1)
    long = pd.Series(0.001 + 0.02 * rng.standard_normal(500), index=pd.date_range("2024-01-01", periods=500, freq="D", tz="UTC"))
    full = metrics(long, pd.Series(0.5, index=long.index))
    assert full["sharpe"] == pytest.approx(sharpe_of(long.to_numpy())) and full["sortino"] > 0 and full["avg_exposure_pct"] == 50.0
    assert full["days_invested_pct"] == 100.0 and full["vol_ann_pct"] > 0


def test_bootstrap_is_reproducible_pairs_blocks_and_detects_a_real_difference() -> None:
    rng = np.random.default_rng(4)
    idx = pd.date_range("2020-01-01", periods=1500, freq="D", tz="UTC")
    base = pd.Series(0.02 * rng.standard_normal(1500), index=idx)
    better = base + 0.002
    noisy = base + pd.Series(0.002 * rng.standard_normal(1500), index=idx)
    a = paired_sharpe_bootstrap(better, base, 20, 500, seed=1)
    assert a == paired_sharpe_bootstrap(better, base, 20, 500, seed=1)
    assert a.ci_low > 0 and a.p_value < 0.05 and a.diff == pytest.approx(a.sharpe_a - a.sharpe_b)
    assert paired_sharpe_bootstrap(better, base, 20, 500, seed=2).ci_low != a.ci_low
    n = paired_sharpe_bootstrap(noisy, base, 20, 500, seed=1)
    assert n.ci_low < 0 < n.ci_high and n.p_value > 0.05
    tiny = paired_sharpe_bootstrap(better.iloc[:100], base.iloc[:100], 20, 100, seed=1)
    assert np.isnan(tiny.diff) and tiny.n == 100  # amostra insuficiente: nada de IC
    idx2 = block_indices(10, 4, 3, np.random.default_rng(0))
    assert idx2.shape == (3, 10) and idx2.max() < 10


def test_holm_and_effective_sample_size() -> None:
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm_adjust([0.5, float("nan"), 0.01])[0] == pytest.approx(0.5) and np.isnan(holm_adjust([0.5, float("nan")])[1])
    rng = np.random.default_rng(2)
    iid = rng.standard_normal(2000)
    ar = np.zeros(2000)
    for i in range(1, 2000):
        ar[i] = 0.9 * ar[i - 1] + rng.standard_normal()
    assert effective_sample_size(iid) > 0.6 * 2000 and effective_sample_size(ar) < 0.2 * 2000
    assert effective_sample_size(np.zeros(50)) == 50


# ---------------------------------------------------------------------------------------------
# Registro de experimentos e reprodutibilidade do estudo
# ---------------------------------------------------------------------------------------------

def record(exp_id: str = "abc", digest: str = "d1") -> dict[str, object]:
    base: dict[str, object] = {c: "x" for c in REGISTRY_SCHEMA}
    base.update({
        "experiment_id": exp_id, "results_digest": digest, "created_at": pd.Timestamp("2026-10-16", tz="UTC"),
        "working_tree_dirty": True, "period_start": pd.Timestamp("2021-01-01", tz="UTC"),
        "period_end": pd.Timestamp("2026-10-15", tz="UTC"),
        "seed": 1, "bootstrap_block": 20, "bootstrap_resamples": 100, "n_policies": 5, "n_variants": 11, "n_hypotheses": 20,
    })
    return base


def test_registry_is_append_only_and_detects_non_reproducible_results(tmp_path: Path) -> None:
    path = tmp_path / "experiments.parquet"
    assert read_registry(path).empty
    assert append_experiment(record("a", "d1"), path) == NEW
    assert append_experiment(record("a", "d1"), path) == REPRODUCED
    assert append_experiment(record("b", "d2"), path) == NEW
    before = read_registry(path)
    with pytest.raises(ExperimentConflict):
        append_experiment(record("a", "OUTRO"), path)
    pd.testing.assert_frame_equal(read_registry(path), before)
    assert before["experiment_id"].tolist() == ["a", "b"]
    incomplete = record("c")
    del incomplete["seed"]
    with pytest.raises(ValueError, match="incompleto"):
        append_experiment(incomplete, path)


def test_ids_fingerprints_and_digests_are_deterministic_and_sensitive() -> None:
    candles = world(300)
    fp = data_fingerprint(candles)
    assert fp == data_fingerprint(candles.sample(frac=1.0, random_state=1))
    changed = candles.copy()
    changed.loc[changed.index[10], "close"] *= 1.0001
    assert data_fingerprint(changed) != fp
    cfg = {"seed": 1, "x": [1, 2]}
    assert experiment_id(cfg, fp) == experiment_id(dict(cfg), fp)
    assert experiment_id({**cfg, "seed": 2}, fp) != experiment_id(cfg, fp) and experiment_id(cfg, "outro") != experiment_id(cfg, fp)
    frame = pd.DataFrame({"k": ["a", "b"], "v": [1.0, 2.0]})
    assert results_digest(frame) == results_digest(frame.assign(v=frame["v"] + 1e-11))
    assert results_digest(frame) != results_digest(frame.assign(v=frame["v"] + 1e-6))


def test_study_runs_end_to_end_reproduces_and_labels_the_primary_comparison() -> None:
    candles = world(800)
    as_of = as_of_for(END)
    small = Protocol(resamples=200, sensitivity_blocks=(10,), classifiers=(("classificador confirmacao 3", RegimeRules(confirm_days=3)),),
                     scenarios=(Scenario("base"), Scenario("custo x2", cost_scale=2.0)), include_selection=False,
                     primary_start="2025-01-01")
    first, second = run_study(candles, as_of, small), run_study(candles, as_of, small)
    pd.testing.assert_frame_equal(first.results, second.results)
    assert results_digest(first.results) == results_digest(second.results)
    assert first.n_policies == 5 and first.n_variants == 3 and first.n_hypotheses == 20
    comp = first.results[first.results["section"].eq("comparacao")]
    assert comp["key"].nunique() == 20 and comp["note"].eq("PRIMARIA (pré-registrada)").any()
    primary = comp[comp["note"].eq("PRIMARIA (pré-registrada)")]
    assert set(primary["key"]) == {f"{POLICY_PRIMARY} vs {STRATEGY_SMA200}"}
    holm = comp[comp["metric"].eq("p_holm")].set_index("key")["value"]
    raw = comp[comp["metric"].eq("p_value")].set_index("key")["value"]
    assert ((holm >= raw - 1e-12) | holm.isna()).all()
    assert POLICY_LEARNED in set(first.mappings.columns) | set(first.decisions["policy"])
    assert first.config["policy_version"] and first.config["classifier_version"]


# ---------------------------------------------------------------------------------------------
# Produção intocada
# ---------------------------------------------------------------------------------------------

def test_production_does_not_import_the_research_policy_modules() -> None:
    code = (
        "import sys, src.pipeline, src.transformers.selection, src.transformers.allocation, src.transformers.recommendation, "
        "src.transformers.notification\n"
        "bad = [m for m in sys.modules if m.startswith(('src.transformers.regime_policy', 'src.transformers.policy_', 'src.loaders.experiment_log'))]\n"
        "print(','.join(bad))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
    source = (ROOT / "src" / "pipeline.py").read_text(encoding="utf-8")
    assert "regime_policy" not in source and "policy_study" not in source


# ---------------------------------------------------------------------------------------------
# Qualidade da evidência e catálogo de estratégias
# ---------------------------------------------------------------------------------------------

def _comparison(diff: float, lo: float, hi: float, n: int = 2000) -> SharpeComparison:
    return SharpeComparison(n, float(n), 1.0, 1.0 - diff, diff, lo, hi, 0.01, 20, 100, 0)


def test_evidence_grade_never_reaches_confirmed_without_a_prospective_period() -> None:
    assert classify_evidence(_comparison(float("nan"), float("nan"), float("nan"), 100), 1.0) == "INSUFICIENTE"
    assert classify_evidence(_comparison(-0.07, -0.2, 0.06), 1.0) == "SEM_EVIDENCIA"
    assert classify_evidence(_comparison(0.5, 0.1, 0.9), 0.001) == "INDICIO_EXPLORATORIO"  # significativo, mas não prospectivo
    assert classify_evidence(_comparison(0.5, 0.1, 0.9), 0.2, prospective=True) == "INDICIO_EXPLORATORIO"
    assert classify_evidence(_comparison(0.5, 0.1, 0.9), 0.001, prospective=True) == "CONFIRMADO_PROSPECTIVO"
    assert classify_evidence(_comparison(-0.5, -0.9, -0.1), 0.001) == "INDICIO_EXPLORATORIO"  # contra também é só indício


def test_every_strategy_name_used_by_the_engines_is_in_the_catalog_and_none_is_confirmed() -> None:
    from src.transformers import selection_backtest, trade_simulator
    from src.transformers.strategy_catalog import BY_NAME, CATALOG, KINDS, confirmed_robust

    used = {v for k, v in vars(selection_backtest).items() if k.startswith("STRATEGY_") and isinstance(v, str)}
    used |= {v for k, v in vars(trade_simulator).items() if k.startswith("STRATEGY_") and isinstance(v, str)}
    used |= set(POLICY_NAMES) | {CASH}
    assert used <= set(BY_NAME), sorted(used - set(BY_NAME))
    assert confirmed_robust() == ()  # conclusão histórica: nenhuma estratégia confirmada como robusta
    assert all(e.kind in KINDS and e.description for e in CATALOG)


def test_study_grades_every_family_comparison() -> None:
    first = run_study(world(800), as_of_for(END), Protocol(
        resamples=100, sensitivity_blocks=(10,), classifiers=(), scenarios=(Scenario("base"),), include_selection=False,
        primary_start="2025-01-01"))
    grades = first.results[first.results["section"].eq("evidencia")]
    assert len(grades) == 20 and set(grades["note"]) <= {"INSUFICIENTE", "SEM_EVIDENCIA", "INDICIO_EXPLORATORIO"}
