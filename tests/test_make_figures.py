"""Preparação pura das figuras: sem desenhar nada."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.make_figures import SHARPE_DELTAS, Interval, ai_intervals, pt, significant, sma200_bars  # noqa: E402


def test_significant_flags_intervals_that_exclude_zero() -> None:
    assert significant(Interval("a", 0.7, 0.1, 1.2))
    assert significant(Interval("b", -0.8, -1.3, -0.3))
    assert not significant(Interval("c", 0.1, -0.4, 0.5))


def test_sharpe_table_is_consistent() -> None:
    for item in SHARPE_DELTAS:
        assert item.low <= item.value <= item.high


def test_pt_uses_comma_and_true_minus() -> None:
    assert pt(8.19, 1, sign=True) == "+8,2"
    assert pt(-2.58, 2) == "−2,58"


def test_sma200_bars_keeps_both_metrics() -> None:
    table = pd.DataFrame({
        "metric": ["max_drawdown", "volatility", "other"], "mean_hold": [0.8, 1.2, 0.0], "mean_strategy": [0.65, 0.9, 0.0],
        "reduction": [0.15, 0.3, 0.0], "ci_low": [0.04, 0.2, 0.0], "ci_high": [0.23, 0.4, 0.0], "n_coins": [47, 47, 47],
        "test_n_coins": [24, 24, 24], "test_reduction": [0.2, 0.4, 0.0],
    })
    out = sma200_bars(table)
    assert out["metric"].tolist() == ["Queda máxima", "Oscilação anual"]
    assert (out["sma200"] < out["hold"]).all()


def test_ai_intervals_converts_to_percentage_points() -> None:
    ranking = pd.DataFrame({
        "model": ["G_GBM_SEM_FNG", "G_GBM_SEM_FNG", "OUTRO"], "metric": ["top_k_vs_universo"] * 3,
        "period": ["DESENVOLVIMENTO", "TESTE_FINAL", "TESTE_FINAL"], "n_days": [10.0, 5.0, 5.0],
        "mean": [0.019, 0.026, 0.1], "ci_low": [-0.004, 0.009, 0.0], "ci_high": [0.041, 0.046, 0.2],
    })
    out = ai_intervals(ranking)
    assert len(out) == 2
    assert abs(out["mean"].iloc[0] - 1.9) < 1e-9
