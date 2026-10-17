"""Motor único de backtest: execução no fechamento seguinte ao sinal, custos e concordância entre os adaptadores."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.backtest_engine import EXECUTION_LAG, simulate_weights
from src.transformers.selection_backtest import run_weighted
from src.transformers.trade_simulator import run_portfolio

FEE = 0.001


def idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")


def test_default_executes_at_the_close_after_the_signal() -> None:
    i = idx(5)
    returns = pd.DataFrame({"A": [0.0, 0.10, 0.20, 0.30, 0.0]}, index=i)
    cost = pd.DataFrame({"A": [0.0] * 5}, index=i)
    targets = pd.DataFrame({"A": [1.0]}, index=i[:1])  # sinal no fechamento do dia 0
    assert EXECUTION_LAG == 1
    run = simulate_weights(targets, returns, cost, i[0], i[-1], band=0.0)
    # executa no fechamento do dia 1 (preço do dia 1 já passou: não ganha 10%) e rende a partir do dia 2
    assert run.daily.iloc[1] == 0.0
    assert run.daily.iloc[2] == pytest.approx(0.20)
    assert run.daily.iloc[3] == pytest.approx(0.30)
    legacy = simulate_weights(targets, returns, cost, i[0], i[-1], band=0.0, execution_lag=0)
    assert legacy.daily.iloc[1] == pytest.approx(0.10)  # a versão antiga executava no próprio fechamento do sinal


def test_lag_one_equals_legacy_with_targets_moved_one_day() -> None:
    rng = np.random.default_rng(1)
    i = idx(60)
    returns = pd.DataFrame(rng.standard_normal((60, 3)) * 0.02, index=i, columns=list("ABC"))
    cost = pd.DataFrame(0.002, index=i, columns=list("ABC"))
    days = i[::5][:-1]
    targets = pd.DataFrame(rng.dirichlet(np.ones(3), size=len(days)) * 0.9, index=days, columns=list("ABC"))
    new = simulate_weights(targets, returns, cost, i[0], i[-1])
    moved = targets.set_axis(targets.index + pd.Timedelta(days=1), axis=0)
    old = simulate_weights(moved, returns, cost, i[0], i[-1], execution_lag=0)
    pd.testing.assert_series_equal(new.daily, old.daily)
    assert new.cost == pytest.approx(old.cost)


def test_engine_has_no_lookahead() -> None:
    """Mudar retornos e alvos DEPOIS do dia d não altera nenhum resultado até d."""
    rng = np.random.default_rng(2)
    i = idx(80)
    returns = pd.DataFrame(rng.standard_normal((80, 2)) * 0.03, index=i, columns=list("AB"))
    cost = pd.DataFrame(0.001, index=i, columns=list("AB"))
    days = i[::4]
    targets = pd.DataFrame(rng.dirichlet(np.ones(2), size=len(days)) * 0.8, index=days, columns=list("AB"))
    cut = i[40]
    base = simulate_weights(targets, returns, cost, i[0], i[-1])
    r2 = returns.copy()
    r2.loc[r2.index > cut] = rng.standard_normal(r2.loc[r2.index > cut].shape) * 0.5
    t2 = targets.copy()
    t2.loc[t2.index > cut] = 1.0
    changed = simulate_weights(t2, r2, cost, i[0], i[-1])
    pd.testing.assert_series_equal(base.daily.loc[:cut], changed.daily.loc[:cut])
    # alvos novos só depois de `cut` (retornos iguais): o alvo decidido em cut+1 executa em cut+2, então o retorno
    # de cut+2 ainda não depende dele
    only_targets = simulate_weights(t2, returns, cost, i[0], i[-1])
    stop = cut + pd.Timedelta(days=2)
    pd.testing.assert_series_equal(base.daily.loc[:stop], only_targets.daily.loc[:stop])


def test_portfolio_and_weighted_engines_agree_on_synthetic_cases() -> None:
    rng = np.random.default_rng(3)
    n = 120
    i = idx(n)
    cols = ["A", "B", "C"]
    returns = pd.DataFrame(rng.standard_normal((n, 3)) * 0.02, index=i, columns=cols)
    valid = pd.DataFrame(True, index=i, columns=cols)
    valid.loc[i[:10], "C"] = False  # C só existe a partir do dia 10
    positions = pd.DataFrame(
        {"A": ([1.0] * 20 + [0.0] * 10) * 4, "B": ([0.0] * 15 + [1.0] * 15) * 4, "C": ([1.0] * 12 + [0.0] * 18) * 4},
        index=i,
    )
    start, end = i[0], i[-1]
    for lag in (0, 1, 2):
        port = run_portfolio(positions, returns, valid, start, end, FEE, execution_lag=lag)
        n_valid = valid.sum(axis=1).astype(float)
        targets = positions.where(valid).fillna(0.0).div(n_valid, axis=0)
        cost = pd.DataFrame(FEE, index=i, columns=cols)
        wgt = run_weighted(targets, returns, cost, start, end, band=0.0, execution_lag=lag)
        pd.testing.assert_series_equal(port.daily, wgt.daily)
        assert float(port.fee_cost.sum()) == pytest.approx(wgt.cost)


def test_both_engines_share_costs_and_have_no_free_trades() -> None:
    i = idx(6)
    returns = pd.DataFrame({"A": [0.0] * 6}, index=i)
    valid = pd.DataFrame({"A": [True] * 6}, index=i)
    positions = pd.DataFrame({"A": [0.0, 1.0, 1.0, 0.0, 0.0, 0.0]}, index=i)
    run = run_portfolio(positions, returns, valid, i[0], i[-1], FEE)
    assert float(run.daily.sum()) == pytest.approx(-2 * FEE, rel=1e-3)  # entra e sai: dois lados com preço parado
