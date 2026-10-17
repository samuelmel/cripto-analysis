"""Fase 3: métricas, bootstrap em blocos e correção para comparações múltiplas (casos com resposta conhecida)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.transformers.bootstrap import (
    BootstrapConfig,
    block_length,
    bootstrap_difference,
    bootstrap_statistic,
    make_resampler,
    max_stat_pvalues,
    optimal_block_length,
    sharpe_stat,
    stationary_indices,
)
from src.transformers.metrics import MetricConventions, cagr_rows, drawdown_stats, return_metrics, sharpe_rows
from src.transformers.multiple_testing import holm

IDX = pd.date_range("2020-01-01", periods=800, freq="D", tz="UTC")


def _series(values: np.ndarray, start: str = "2020-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D", tz="UTC"))


def _ar1(n: int, phi: float, seed: int, mu: float = 0.0, sd: float = 0.02) -> np.ndarray:
    rng = np.random.default_rng(seed)
    e = rng.normal(0, sd, n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + e[t]
    return x + mu


# ------------------------------------------------------------------------------ métricas

def test_metrics_match_hand_computed_values() -> None:
    r = _series(np.array([0.10, -0.05, 0.02, 0.0] * 100))
    m = return_metrics(r, pd.Series(1.0, index=r.index))
    growth = float(np.prod(1 + r.to_numpy()))
    assert m["n_obs"] == 400
    assert m["total_return_pct"] == pytest.approx((growth - 1) * 100)
    assert m["cagr_pct"] == pytest.approx((growth ** (365 / 400) - 1) * 100)
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(365))
    downside = math.sqrt(float(np.mean(np.minimum(r.to_numpy(), 0) ** 2)))
    assert m["sortino"] == pytest.approx(r.mean() / downside * math.sqrt(365))
    assert m["vol_pct"] == pytest.approx(r.std(ddof=1) * math.sqrt(365) * 100)
    assert m["exposure_pct"] == pytest.approx(100.0) and m["time_in_market_pct"] == pytest.approx(100.0)
    assert m["calmar"] == pytest.approx(m["cagr_pct"] / abs(m["max_drawdown_pct"]))


def test_drawdown_depth_duration_and_open_flag() -> None:
    r = _series(np.array([0.0, 0.10, -0.50, 0.20, 0.0, 1.0, 0.0]))
    dd, days, still_open = drawdown_stats(r)
    assert dd == pytest.approx(-0.5)
    assert days == 3            # três dias abaixo do topo de 1,10 (−50%, +20%, 0%) até superar
    assert not still_open
    dd2, _, open2 = drawdown_stats(_series(np.array([0.1, -0.2, 0.05])))
    assert dd2 == pytest.approx(-0.2)
    assert open2


def test_small_samples_do_not_get_annualized_or_ratio_estimates() -> None:
    short = _series(np.random.default_rng(1).normal(0.001, 0.02, 100))
    m = return_metrics(short)
    assert math.isnan(m["sharpe"]) and math.isnan(m["sortino"]) and math.isnan(m["vol_pct"])
    assert math.isnan(m["cagr_pct"]) and math.isnan(m["calmar"])
    assert math.isfinite(m["total_return_pct"]) and math.isfinite(m["max_drawdown_pct"])  # descritivas continuam
    mid = return_metrics(_series(np.random.default_rng(1).normal(0.001, 0.02, 200)))
    assert math.isfinite(mid["sharpe"]) and math.isnan(mid["cagr_pct"])  # Sharpe com 180+, anual só com 365+


def test_all_cash_has_zero_sharpe_and_missing_returns_are_rejected() -> None:
    cash = _series(np.zeros(400))
    m = return_metrics(cash, pd.Series(0.0, index=cash.index))
    assert m["sharpe"] == 0.0 and m["sortino"] == 0.0 and m["time_in_market_pct"] == 0.0
    with pytest.raises(ValueError, match="ausente"):
        return_metrics(_series(np.array([0.01, np.nan] * 200)))  # lacuna não vira retorno zero
    assert return_metrics(pd.Series(dtype="float64"))["n_obs"] == 0


def test_vectorized_rows_match_the_scalar_definition() -> None:
    x = np.random.default_rng(3).normal(0.001, 0.03, (5, 400))
    for i in range(5):
        r = _series(x[i])
        m = return_metrics(r)
        assert sharpe_rows(x)[i] == pytest.approx(m["sharpe"])
        assert cagr_rows(x)[i] * 100 == pytest.approx(m["cagr_pct"])
    with pytest.raises(ValueError):
        MetricConventions(min_obs_ratio=1)


# ------------------------------------------------------------------------------ bootstrap

def test_stationary_indices_are_reproducible_circular_blocks_with_the_requested_mean_length() -> None:
    a = stationary_indices(500, 200, 20.0, np.random.default_rng(42))
    b = stationary_indices(500, 200, 20.0, np.random.default_rng(42))
    assert np.array_equal(a, b) and a.shape == (200, 500)
    assert a.min() >= 0 and a.max() < 500
    continues = (np.diff(a, axis=1) % 500) == 1          # dentro do bloco: dia seguinte (circular)
    breaks = (~continues).sum() + a.shape[0]
    mean_block = a.size / breaks
    assert 15 < mean_block < 25
    iid = stationary_indices(500, 50, 1.0, np.random.default_rng(1))
    assert ((np.diff(iid, axis=1) % 500) == 1).mean() < 0.01  # L = 1: cada dia é um bloco


def test_automatic_block_grows_with_serial_dependence() -> None:
    iid = optimal_block_length(np.random.default_rng(0).normal(0, 1, 2000))
    dependent = optimal_block_length(_ar1(2000, 0.8, 0))
    assert iid < 5 < dependent
    assert optimal_block_length(np.zeros(100)) == 1.0
    cfg = BootstrapConfig(block=30.0)
    assert block_length([np.ones(60)], cfg) == pytest.approx(20.0)  # fixo, limitado a n/3


def test_block_bootstrap_ci_is_wider_than_iid_under_autocorrelation() -> None:
    x = _ar1(1500, 0.6, 7, mu=0.001)
    mean = lambda m: m.mean(axis=1)  # noqa: E731
    blocked = bootstrap_statistic(x, mean, make_resampler([x], BootstrapConfig(n_boot=1000, seed=1)))
    naive = bootstrap_statistic(x, mean, make_resampler([x], BootstrapConfig(n_boot=1000, seed=1, block=1.0)))
    assert blocked.block > 3
    assert (blocked.ci_high - blocked.ci_low) > 1.4 * (naive.ci_high - naive.ci_low)


def test_ci_coverage_of_the_mean_is_close_to_nominal_on_ar1() -> None:
    hits = 0
    reps = 120
    for seed in range(reps):
        x = _ar1(600, 0.4, 1000 + seed)
        est = bootstrap_statistic(x, lambda m: m.mean(axis=1), make_resampler([x], BootstrapConfig(n_boot=300, seed=seed)))
        hits += est.ci_low <= 0.0 <= est.ci_high
    assert 0.78 <= hits / reps <= 0.98  # nominal 90%; tolerância para 120 repetições


def test_paired_difference_detects_a_real_edge_and_not_a_fake_one() -> None:
    rng = np.random.default_rng(11)
    common = rng.normal(0.0005, 0.03, 1500)
    better = common + rng.normal(0.002, 0.005, 1500)
    same = common + rng.normal(0.0, 0.005, 1500)
    res = make_resampler([better, common], BootstrapConfig(n_boot=1000, seed=3))
    win = bootstrap_difference(better, common, sharpe_stat(), res)
    assert win.ci_low > 0 and win.p_value < 0.01
    res2 = make_resampler([same, common], BootstrapConfig(n_boot=1000, seed=3))
    null = bootstrap_difference(same, common, sharpe_stat(), res2)
    assert null.ci_low < 0 < null.ci_high and null.p_value > 0.05
    again = bootstrap_difference(better, common, sharpe_stat(), make_resampler([better, common], BootstrapConfig(n_boot=1000, seed=3)))
    assert again.ci_low == win.ci_low and again.p_value == win.p_value  # mesma semente, mesmo resultado


def test_bootstrap_refuses_misaligned_or_missing_data() -> None:
    with pytest.raises(ValueError, match="alinhadas"):
        make_resampler([np.zeros(10), np.zeros(11)], BootstrapConfig())
    with pytest.raises(ValueError, match="ausente"):
        make_resampler([np.array([0.0, np.nan, 0.0])], BootstrapConfig())
    with pytest.raises(ValueError):
        BootstrapConfig(n_boot=10)


def test_max_stat_adjustment_is_never_below_the_raw_p_value() -> None:
    rng = np.random.default_rng(5)
    base = rng.normal(0.0005, 0.03, 1200)
    series = [base + rng.normal(mu, 0.01, 1200) for mu in (0.0, 0.0005, 0.003)]
    res = make_resampler([*series, base], BootstrapConfig(n_boot=800, seed=9))
    est = [bootstrap_difference(s, base, sharpe_stat(), res) for s in series]
    adj = max_stat_pvalues(est)
    for e, a in zip(est, adj, strict=True):
        assert a >= e.p_value - 1e-12
    assert adj[2] < 0.05  # o efeito grande sobrevive ao ajuste


# ------------------------------------------------------------------------------ Holm

def test_holm_matches_the_textbook_example() -> None:
    out = holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005}, alpha=0.05).set_index("hypothesis")
    # ordenados: d .005 (x4=.02), a .01 (x3=.03), c .03 (x2=.06), b .04 (x1=.04 -> max .06)
    assert out.loc["d", "p_holm"] == pytest.approx(0.02)
    assert out.loc["a", "p_holm"] == pytest.approx(0.03)
    assert out.loc["c", "p_holm"] == pytest.approx(0.06)
    assert out.loc["b", "p_holm"] == pytest.approx(0.06)
    assert out["reject"].tolist() == [True, False, False, True]


def test_untested_hypotheses_stay_in_the_family_with_p_one() -> None:
    with_missing = holm({"a": 0.01, "b": float("nan"), "c": 0.02}).set_index("hypothesis")
    assert int(with_missing["family_size"].iloc[0]) == 3
    assert bool(with_missing.loc["b", "untested"]) and not bool(with_missing.loc["b", "reject"])
    assert with_missing.loc["a", "p_holm"] == pytest.approx(0.03)  # m = 3, não 2
    with pytest.raises(ValueError):
        holm({"a": 1.5})
