"""Reconciliação entre o motor único e os dois motores legados, em casos sintéticos.

Mostra onde os motores concordam (mesmas premissas = mesmo resultado) e documenta, com teste, cada diferença de
premissa, em vez de forçar resultados idênticos:
    - sem custos e com abertura(D+1) = fechamento(D), o motor único reproduz `run_portfolio` e `run_weighted`;
    - `run_portfolio` rebalanceava para peso igual todo dia SEM custo: o motor único cobra esse rebalanceamento;
    - `run_weighted` com banda podia passar de 100% de exposição (alavancagem implícita): o motor único não passa;
    - `run_portfolio` perdia o movimento de preço através de um candle ausente: o motor único o registra.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.transformers.backtest_engine import ExecutionConfig, MarketPanel, reconcile, run_backtest, total_costs
from src.transformers.costs import CostModel
from src.transformers.selection_backtest import run_weighted
from src.transformers.trade_simulator import run_portfolio

N = 300
COLS = ["A", "B", "C"]
IDX = pd.date_range("2024-01-01", periods=N, freq="D", tz="UTC")


def _free(fee: float = 0.0, band: float = 0.0) -> ExecutionConfig:
    return ExecutionConfig(costs=CostModel(fee_rate=fee, slippage=0.0, spread_tiers=((0.0, 0.0),)), rebalance_band=band)


def _market(seed: int = 3) -> tuple[pd.DataFrame, MarketPanel]:
    rng = np.random.default_rng(seed)
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, (N, 3)), axis=0)), index=IDX, columns=COLS)
    opens = closes.shift(1).fillna(closes.iloc[0])  # abertura(D+1) = fechamento(D): o tempo de execução não pesa
    return closes, MarketPanel(opens, closes, pd.DataFrame(0.0, index=IDX, columns=COLS))


def _signals(seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    raw = pd.DataFrame(rng.integers(0, 2, (N, 3)).astype(float), index=IDX, columns=COLS)
    return raw.rolling(10, min_periods=1).max().round()  # episódios de vários dias, não ruído diário


def test_without_costs_the_engine_reproduces_run_portfolio_exactly() -> None:
    closes, panel = _market()
    positions = _signals()
    valid = pd.DataFrame(True, index=IDX, columns=COLS)
    legacy = run_portfolio(positions, closes.pct_change(fill_method=None), valid, IDX[0], IDX[-1], fee=0.0)
    new = run_backtest(panel, positions / 3.0, cfg=_free())
    assert reconcile(new) == []
    # dia 0: o legado não tem posição herdada; a partir do dia 1 os retornos coincidem
    np.testing.assert_allclose(new.returns.iloc[1:].to_numpy(), legacy.daily.iloc[1:].to_numpy(), atol=1e-12)


def test_run_portfolio_did_not_charge_the_daily_rebalancing_it_assumed() -> None:
    closes, panel = _market()
    positions = _signals()
    valid = pd.DataFrame(True, index=IDX, columns=COLS)
    fee = 0.001
    legacy = run_portfolio(positions, closes.pct_change(fill_method=None), valid, IDX[0], IDX[-1], fee=fee)
    new = run_backtest(panel, positions / 3.0, cfg=_free(fee=fee))
    legacy_fees = float(legacy.fee_cost.sum())
    new_fees = total_costs(new)["fee"]
    # o legado só cobrava a taxa quando a posição 0/1 mudava; o peso igual diário também exige operar a deriva
    assert new_fees > legacy_fees * 1.05
    assert float(new.equity.iloc[-1]) < float((1 + legacy.daily).prod())


def test_without_costs_the_engine_reproduces_run_weighted_without_band() -> None:
    closes, panel = _market()
    weekly = (_signals() / 3.0).iloc[::7]
    returns = closes.pct_change(fill_method=None)
    zero = pd.DataFrame(0.0, index=IDX, columns=COLS)
    legacy = run_weighted(weekly, returns, zero, IDX[0], IDX[-1], band=0.0)
    new = run_backtest(panel, weekly, cfg=_free())
    np.testing.assert_allclose(new.returns.to_numpy(), legacy.daily.to_numpy(), atol=1e-12)
    assert reconcile(new) == []


def test_run_weighted_with_band_could_exceed_100_percent_exposure_the_engine_cannot() -> None:
    closes, panel = _market(seed=11)
    returns = closes.pct_change(fill_method=None)
    zero = pd.DataFrame(0.0, index=IDX, columns=COLS)
    # Alvo de 1/3 em cada uma, toda semana. Quando UMA moeda sai da banda, o legado a reajusta para 1/3 enquanto
    # as outras ficam com o peso que derivou para cima: a soma passa de 100% sem que haja caixa para isso.
    full = pd.DataFrame(1.0 / 3.0, index=IDX[::7], columns=COLS)
    legacy = run_weighted(full, returns, zero, IDX[0], IDX[-1], band=0.05)
    new = run_backtest(panel, full, cfg=_free(band=0.05))
    assert legacy.exposure.max() > 1.0 + 1e-6      # alavancagem implícita no motor antigo
    assert new.exposure.max() <= 1.0 + 1e-12      # o motor único compra só com o caixa que existe
    assert (new.cash >= 0).all() and reconcile(new) == []


def test_run_portfolio_lost_the_move_across_a_missing_candle() -> None:
    closes = pd.DataFrame({"A": [100.0, 100.0, math.nan, 120.0, 120.0]}, index=IDX[:5])
    opens = pd.DataFrame({"A": [100.0, 100.0, math.nan, 100.0, 120.0]}, index=IDX[:5])
    panel = MarketPanel(opens, closes, pd.DataFrame(0.0, index=IDX[:5], columns=["A"]))
    positions = pd.DataFrame({"A": [1.0] * 5}, index=IDX[:5])
    valid = pd.DataFrame({"A": [True] * 5}, index=IDX[:5])
    legacy = run_portfolio(positions, closes.pct_change(fill_method=None), valid, IDX[0], IDX[4], fee=0.0)
    new = run_backtest(panel, positions, cfg=_free())
    assert float((1 + legacy.daily).prod()) == pytest.approx(1.0)  # os +20% sumiram junto com o candle ausente
    assert float(new.equity.iloc[-1]) == pytest.approx(1.2)        # o motor único marca o preço quando ele volta
    assert reconcile(new) == []
