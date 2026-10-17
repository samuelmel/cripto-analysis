"""Fase 3: protocolo temporal, ausência de look-ahead, escolha sem o teste, registro de experimentos e classificação."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.loaders.experiment_store import DuplicateRunError, append_table, read_table
from src.transformers.anomaly_detector import classify_history
from src.transformers.backtest_engine import ExecutionConfig, panel_from_candles, run_backtest
from src.transformers.bootstrap import BootstrapConfig
from src.transformers.costs import CostModel
from src.transformers.data_quality import clean_candles
from src.transformers.evidence import (
    CATEGORY_INSUFFICIENT,
    CATEGORY_INVALID,
    CATEGORY_NEGATIVE,
    CATEGORY_PROMISING,
    CATEGORY_ROBUST,
    EvidenceInput,
    classify,
)
from src.transformers.experiments import ExperimentSpec, MixedExperimentError, assert_comparable, registry_rows
from src.transformers.metrics import engine_metrics
from src.transformers.portfolio_backtest import equal_weight, investable_mask
from src.transformers.selection import compute_features, regime_series
from src.transformers.selection_backtest import baseline_targets, evidence_with_uncertainty, evaluate_selection_runs, selection_targets
from src.transformers.strategies import market_from_candles
from src.transformers.strategy_catalog import core_signals, trend_signal
from src.transformers.trade_simulator import trend_positions, wide
from src.transformers.validation import Benchmark, Case, ValidationSetup, evaluate_family
from src.transformers.walk_forward import (
    STATUS_EXPLORED,
    STATUS_PROSPECTIVE,
    Fold,
    HoldoutViolation,
    WalkForwardPlan,
    assign_decisions,
    check_folds,
    delay_targets,
    make_folds,
    select_per_fold,
    stitch_targets,
)
from tests.synthetic_market import synthetic_candles, synthetic_fng

UTC = "UTC"


def ts(day: str) -> pd.Timestamp:
    return pd.Timestamp(day, tz=UTC)


PLAN = WalkForwardPlan(ts("2017-08-17"), ts("2020-01-01"), ts("2026-06-30"), explored_until=ts("2026-06-30"))


@pytest.fixture(scope="module")
def market() -> dict[str, object]:
    candles = clean_candles(synthetic_candles())
    history = classify_history(candles, synthetic_fng(candles))
    return {"candles": candles, "history": history, "features": compute_features(market_from_candles(candles)),
            "panel": panel_from_candles(candles, CostModel())}


# ------------------------------------------------------------------------------ dobras

def test_folds_are_annual_anchored_and_never_overlap_the_choice() -> None:
    folds = make_folds(PLAN)
    assert [f.label for f in folds] == ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
    for f in folds:
        assert f.train_start == PLAN.data_start and f.train_end == f.test_start - pd.Timedelta(days=1)
        assert (f.train_end - f.validation_start).days + 1 == 730
        assert f.data_status == STATUS_EXPLORED
    assert folds[-1].test_end == ts("2026-06-30")
    for a, b in zip(folds, folds[1:], strict=False):
        assert b.test_start == a.test_end + pd.Timedelta(days=1)


def test_embargo_and_prospective_status() -> None:
    plan = WalkForwardPlan(ts("2017-08-17"), ts("2020-01-01"), ts("2026-06-30"), explored_until=ts("2023-06-30"), embargo_days=5)
    folds = make_folds(plan)
    assert all((f.test_start - f.train_end).days == 6 for f in folds)
    assert [f.data_status for f in folds][-3:] == [STATUS_PROSPECTIVE] * 3  # 2024, 2025, 2026: depois do explorado


def test_overlapping_or_short_windows_are_rejected() -> None:
    f = make_folds(PLAN)[0]
    bad = Fold(0, "x", f.train_start, f.validation_start, f.test_start, f.test_start, f.test_end, STATUS_EXPLORED)
    with pytest.raises(HoldoutViolation):
        check_folds([bad])
    with pytest.raises(HoldoutViolation):
        make_folds(WalkForwardPlan(ts("2019-06-01"), ts("2020-01-01"), ts("2021-01-01"), explored_until=ts("2021-01-01")))


def test_decisions_use_only_parameters_chosen_before_them() -> None:
    folds = make_folds(PLAN)
    days = pd.DatetimeIndex([ts("2019-12-30"), ts("2019-12-31"), ts("2020-06-01"), ts("2020-12-31"), ts("2021-01-01")])
    assert assign_decisions(days, folds).tolist() == [-1, 0, 0, 1, 1]  # antes da 1ª escolha: sem parâmetro (caixa)


# ------------------------------------------------------------------------------ escolha sem ver o teste

def test_grid_choice_ignores_prices_inside_the_test_window(market: dict[str, object]) -> None:
    """Adulterar os preços do teste de uma dobra não muda a escolha dessa dobra: só a validação decide."""
    history = market["history"]
    assert isinstance(history, pd.DataFrame)
    core = ["BTC/USDT", "ETH/USDT"]
    inv = investable_mask(history, None)[core]
    candidates = {f"sma{n}": equal_weight(trend_signal(history, n, None)[core], inv) for n in (100, 200, 300)}
    folds = make_folds(PLAN)
    panel = market["panel"]

    def chooser(p: object) -> pd.DataFrame:
        from src.transformers.backtest_engine import MarketPanel
        assert isinstance(p, MarketPanel)

        def score(t: pd.DataFrame, s: pd.Timestamp, e: pd.Timestamp) -> tuple[float, bool]:
            assert t.index.max() <= e  # o avaliador nunca recebe decisões do teste
            m = engine_metrics(run_backtest(MarketPanel(p.open[core], p.close[core], p.half_spread[core]), t, start=s, end=e))
            v = m["sharpe"]
            return (float(v) if isinstance(v, float) else math.nan), True
        return select_per_fold(candidates, folds, score)

    original = chooser(panel)
    from src.transformers.backtest_engine import MarketPanel
    assert isinstance(panel, MarketPanel)
    f = folds[3]
    tamper = (panel.close.index >= f.test_start) & (panel.close.index <= f.test_end)
    noisy = MarketPanel(panel.open.mul(np.where(tamper, 3.0, 1.0), axis=0), panel.close.mul(np.where(tamper, 3.0, 1.0), axis=0),
                        panel.half_spread)
    tampered = chooser(noisy)
    pick = lambda s, k: s[(s["fold"] == k) & s["chosen"]]["candidate"].iloc[0]  # noqa: E731
    for k in range(0, 4):  # dobras até a adulterada (inclusive) escolhem igual
        assert pick(original, k) == pick(tampered, k)
    stitched = stitch_targets(candidates, original, folds)
    assert stitched.loc[: folds[0].train_end - pd.Timedelta(days=1)].to_numpy().sum() == 0  # sem escolha: caixa


def test_delay_shifts_decisions_by_whole_days() -> None:
    t = pd.DataFrame({"A": [1.0, 0.0]}, index=pd.DatetimeIndex([ts("2024-01-01"), ts("2024-01-08")]))
    assert delay_targets(t, 1).index.tolist() == [ts("2024-01-02"), ts("2024-01-09")]
    with pytest.raises(ValueError):
        delay_targets(t, -1)


# ------------------------------------------------------------------------------ look-ahead dos sinais

@pytest.mark.parametrize("cut", ["2021-06-30", "2023-03-15", "2025-01-01"])
def test_truncating_after_d_changes_no_signal_or_selection_up_to_d(market: dict[str, object], cut: str) -> None:
    candles = market["candles"]
    assert isinstance(candles, pd.DataFrame)
    d = ts(cut)
    short = candles[candles["timestamp"].le(d)]
    full_h = market["history"]
    short_h = classify_history(short, synthetic_fng(short))
    assert isinstance(full_h, pd.DataFrame)
    core = ["BTC/USDT", "ETH/USDT"]
    full_specs = core_signals(full_h[full_h["symbol"].isin(core)], market_from_candles(candles[candles["symbol"].isin(core)]))
    short_specs = core_signals(short_h[short_h["symbol"].isin(core)], market_from_candles(short[short["symbol"].isin(core)]))
    for a, b in zip(full_specs, short_specs, strict=True):
        frames = {"": a.signal} if a.signal is not None else dict(a.grid)
        others = {"": b.signal} if b.signal is not None else dict(b.grid)
        for key, frame in frames.items():
            assert frame is not None
            other = others[key]
            assert other is not None
            pd.testing.assert_frame_equal(frame.loc[:d], other.loc[:d], check_freq=False, obj=f"{a.name} {key}")
    features = market["features"]
    assert isinstance(features, pd.DataFrame)
    short_f = compute_features(market_from_candles(short))
    days = list(pd.date_range(d - pd.Timedelta(days=70), d, freq="7D"))
    full_sel = selection_targets(features, regime_series(features), days, 100.0)
    short_sel = selection_targets(short_f, regime_series(short_f), days, 100.0)
    pd.testing.assert_frame_equal(full_sel.variable, short_sel.variable.reindex(columns=full_sel.variable.columns, fill_value=0.0))
    full_b = baseline_targets(features, "BTC/USDT", days, 3)
    short_b = baseline_targets(short_f, "BTC/USDT", days, 3)
    for name, frame in full_b.items():
        pd.testing.assert_frame_equal(frame, short_b[name].reindex(columns=frame.columns, fill_value=0.0), obj=name)


def test_catalog_trend_is_the_panel_rule(market: dict[str, object]) -> None:
    h = market["history"]
    assert isinstance(h, pd.DataFrame)
    pd.testing.assert_frame_equal(trend_signal(h), trend_positions(h).reindex_like(wide(h, "close")).fillna(0.0))


# ------------------------------------------------------------------------------ família no motor (sintético)

def _family(market: dict[str, object], boot: BootstrapConfig) -> tuple[list[Case], list[Benchmark], ValidationSetup]:
    history = market["history"]
    panel = market["panel"]
    assert isinstance(history, pd.DataFrame)
    from src.transformers.backtest_engine import MarketPanel
    assert isinstance(panel, MarketPanel)
    core = ["BTC/USDT", "ETH/USDT"]
    inv = investable_mask(history, None)[core]
    cfg = ExecutionConfig()
    plan = WalkForwardPlan(ts("2017-08-17"), ts("2021-01-01"), ts("2026-06-30"), explored_until=ts("2026-06-30"))
    folds = make_folds(plan)
    hold = Benchmark("HOLD", "P", cfg, equal_weight(pd.DataFrame(1.0, index=inv.index, columns=core), inv))
    cases = [
        Case("TENDENCIA", "P", "HOLD", cfg, equal_weight(trend_signal(history)[core], inv),
             variants={"sma150": equal_weight(trend_signal(history, 150)[core], inv)}),
        Case("SEM_FNG", "P", "HOLD", cfg, equal_weight(trend_signal(history)[core], inv), invalid_reason="Fear & Greed ausente"),
    ]
    setup = ValidationSetup(panel=panel, folds=folds, boot=boot, regimes=regime_series(market["features"]))  # type: ignore[arg-type]
    return cases, [hold], setup


def test_family_evaluation_is_complete_reproducible_and_flags_invalid_tests(market: dict[str, object]) -> None:
    cases, benchmarks, setup = _family(market, BootstrapConfig(n_boot=200, seed=1))
    a = evaluate_family(cases, benchmarks, setup)
    b = evaluate_family(cases, benchmarks, setup)
    pd.testing.assert_frame_equal(a.summary, b.summary)  # mesma semente e dados: mesmo resultado
    s = a.summary.set_index("strategy")
    assert s.loc["SEM_FNG", "category"] == CATEGORY_INVALID
    assert s.loc["SEM_FNG", "p_holm"] == 1.0                     # continua na família, com p = 1
    assert s.loc["TENDENCIA", "category"] in {CATEGORY_INSUFFICIENT, CATEGORY_NEGATIVE, CATEGORY_PROMISING, CATEGORY_ROBUST}
    assert s.loc["TENDENCIA", "p_holm"] >= s.loc["TENDENCIA", "p_value"]
    assert s.loc["TENDENCIA", "delta_sharpe_ci_low"] <= s.loc["TENDENCIA", "delta_sharpe"] <= s.loc["TENDENCIA", "delta_sharpe_ci_high"]
    assert set(a.scenarios["scenario"]) >= {"BASE", "CUSTO_ALTO", "ATRASO_1D", "INICIO_EM_CAIXA", "DESLISTAGEM_100", "DADOS_PARCIAIS"}
    assert len(a.folds) == 6 and set(a.blocks["block"]) >= {5.0, 20.0, 60.0}
    high = a.scenarios.set_index(["strategy", "scenario"]).loc[("TENDENCIA", "CUSTO_ALTO")]
    low = a.scenarios.set_index(["strategy", "scenario"]).loc[("TENDENCIA", "CUSTO_BAIXO")]
    assert high["cagr_pct"] < low["cagr_pct"]                    # custo maior, retorno menor


def test_strategy_and_benchmark_must_share_the_execution_premises(market: dict[str, object]) -> None:
    cases, benchmarks, setup = _family(market, BootstrapConfig(n_boot=100))
    other = Case("BANDA", "P", "HOLD", ExecutionConfig(rebalance_band=0.05), cases[0].targets)
    with pytest.raises(ValueError, match="premissas"):
        evaluate_family([other], benchmarks, setup)
    with pytest.raises(ValueError, match="não declarada"):
        evaluate_family([Case("X", "P", "NADA", ExecutionConfig(), cases[0].targets)], benchmarks, setup)


def test_pipeline_evidence_reports_uncertainty_and_never_calls_the_period_untouched(market: dict[str, object]) -> None:
    features, panel = market["features"], market["panel"]
    assert isinstance(features, pd.DataFrame)
    periods = {"TESTE": (ts("2023-01-01"), ts("2026-06-30"))}
    perf, _, runs = evaluate_selection_runs(features, regime_series(features), periods, 100.0, 7, panel, ExecutionConfig())  # type: ignore[arg-type]
    text = evidence_with_uncertainty(perf, runs, "TESTE", BootstrapConfig(n_boot=200))
    assert "não é um teste intocado" in text and "intervalo de 90%" in text and "fora da amostra" not in text
    assert evidence_with_uncertainty(perf.iloc[0:0], runs, "TESTE").startswith("Sem validação")


# ------------------------------------------------------------------------------ registro

def _spec(**over: object) -> ExperimentSpec:
    base: dict[str, object] = dict(family="f", strategy="S", params={"n": 20}, universe="P", benchmark="HOLD", scenario="BASE",
                                   period_start=ts("2020-01-01"), period_end=ts("2026-06-30"), data_status=STATUS_EXPLORED,
                                   execution_version="next-open-v1", costs=CostModel(), rebalance_band=0.0, delist_recovery=0.0,
                                   data_fingerprint="abc", config_fingerprint="cfg")
    base.update(over)
    return ExperimentSpec(**base)  # type: ignore[arg-type]


def test_experiment_id_is_deterministic_and_covers_data_and_premises() -> None:
    assert _spec().experiment_id == _spec().experiment_id
    assert _spec().experiment_id == _spec(limitations=("nota",)).experiment_id
    for change in ({"data_fingerprint": "xyz"}, {"execution_version": "legado"}, {"params": {"n": 55}},
                   {"costs": CostModel(fee_rate=0.002)}, {"scenario": "CUSTO_ALTO"}, {"period_end": ts("2026-07-01")}):
        assert _spec(**change).experiment_id != _spec().experiment_id


def test_registry_is_append_only_and_flags_reproduction(tmp_path: Path) -> None:
    rows1 = registry_rows([(_spec(), {"sharpe": 1.0}, {}, "X", "VALIDO")], "run1", ts("2026-10-16 12:00"))
    append_table("registry", rows1, tmp_path)
    with pytest.raises(DuplicateRunError):
        append_table("registry", rows1, tmp_path)               # nunca sobrescreve uma execução
    previous = read_table("registry", tmp_path)
    same = registry_rows([(_spec(), {"sharpe": 1.0}, {}, "X", "VALIDO")], "run2", ts("2026-10-17"), previous)
    diff = registry_rows([(_spec(), {"sharpe": 0.5}, {}, "X", "VALIDO")], "run3", ts("2026-10-17"), previous)
    assert bool(same["reproduces"].iloc[0]) and not bool(diff["reproduces"].iloc[0])
    assert pd.isna(rows1["reproduces"].iloc[0])
    append_table("registry", same, tmp_path)
    stored = read_table("registry", tmp_path)
    assert stored["run_id"].tolist() == ["run1", "run2"]       # as duas execuções preservadas
    assert stored["data_fingerprint"].eq("abc").all() and stored["execution_version"].eq("next-open-v1").all()
    with pytest.raises(ValueError, match="run_id"):
        append_table("summary", pd.DataFrame({"x": [1]}), tmp_path)


def test_mixing_engines_or_data_in_one_comparison_is_refused() -> None:
    a = registry_rows([(_spec(), {}, {}, "", "VALIDO")], "r", ts("2026-10-16"))
    b = registry_rows([(_spec(strategy="T", execution_version="legado-run_portfolio"), {}, {}, "", "VALIDO")], "r", ts("2026-10-16"))
    assert_comparable(pd.concat([a, a]))
    with pytest.raises(MixedExperimentError, match="execution_version"):
        assert_comparable(pd.concat([a, b]))
    c = registry_rows([(_spec(strategy="U", data_fingerprint="outro"), {}, {}, "", "VALIDO")], "r", ts("2026-10-16"))
    with pytest.raises(MixedExperimentError, match="data_fingerprint"):
        assert_comparable(pd.concat([a, c]))


# ------------------------------------------------------------------------------ classificação

def _ev(**over: object) -> EvidenceInput:
    base: dict[str, object] = dict(invalid_reason=None, n_obs=2400, n_entries=40, timing=True, delta_sharpe=0.5, ci_low=0.1,
                                   ci_high=0.9, p_holm=0.01, positive_fold_share=0.8, stress_min_delta=0.2,
                                   variant_positive_share=1.0, cagr_pct=20.0, max_drawdown_pct=-30.0,
                                   benchmark_max_drawdown_pct=-60.0)
    base.update(over)
    return EvidenceInput(**base)  # type: ignore[arg-type]


def test_robust_requires_every_criterion() -> None:
    assert classify(_ev())[0] == CATEGORY_ROBUST
    for change in ({"p_holm": 0.2}, {"positive_fold_share": 0.5}, {"stress_min_delta": -0.01}, {"variant_positive_share": 0.5},
                   {"variant_positive_share": float("nan")}, {"cagr_pct": -1.0}, {"max_drawdown_pct": -70.0}):
        category, reasons = classify(_ev(**change))
        assert category == CATEGORY_PROMISING and reasons


def test_luck_small_samples_negative_and_invalid_are_separated() -> None:
    assert classify(_ev(ci_low=-0.1))[0] == CATEGORY_INSUFFICIENT                       # compatível com sorte
    assert classify(_ev(n_obs=500))[0] == CATEGORY_INSUFFICIENT                         # amostra curta
    assert classify(_ev(n_entries=3))[0] == CATEGORY_INSUFFICIENT                       # poucas operações
    assert classify(_ev(n_entries=3, timing=False))[0] == CATEGORY_ROBUST               # sem timing: entradas não contam
    neg, why = classify(_ev(delta_sharpe=-0.3, ci_low=-0.8, ci_high=-0.1))
    assert neg == CATEGORY_NEGATIVE and "significativamente" in why[0]
    assert classify(_ev(invalid_reason="feature ausente"))[0] == CATEGORY_INVALID
