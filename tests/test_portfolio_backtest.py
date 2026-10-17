"""Estratégias de referência no motor único: operações da tendência e carteira com premissas comuns."""

from __future__ import annotations

import pandas as pd
import pytest

from src.transformers.anomaly_detector import classify_history
from src.transformers.backtest_engine import ExecutionConfig, panel_from_candles
from src.transformers.costs import CostModel
from src.transformers.portfolio_backtest import performance_summary, trend_trades
from src.transformers.trade_simulator import EXIT_TREND, PERFORMANCE_SCHEMA, STATUS_CLOSED, TRADE_SCHEMA
from tests.helpers import make_candles, ramp

NO_FNG = pd.DataFrame()
COSTS = CostModel(fee_rate=0.001, slippage=0.0005, spread_tiers=((0.0, 0.0005),))


def _with_gap_opens(candles: pd.DataFrame) -> pd.DataFrame:
    """Abertura = fechamento do dia anterior + 1 (diferente do fechamento que gerou o sinal)."""
    c = candles.sort_values(["symbol", "timestamp"]).copy()
    c["open"] = c.groupby("symbol")["close"].shift(1).fillna(c["close"]) + 1.0
    c["high"] = c[["open", "close"]].max(axis=1)
    c["low"] = c[["open", "close"]].min(axis=1)
    return c


def _rise_then_fall() -> pd.DataFrame:
    btc = [100.0] * 200 + ramp(101, 160, 60) + ramp(159, 60, 60)
    return _with_gap_opens(make_candles({"BTC/USDT": btc}, "2026-06-30", quote_volume=1e9))


def test_trend_trade_enters_and_exits_at_the_next_open_with_costs() -> None:
    candles = _rise_then_fall()
    history = classify_history(candles, NO_FNG)
    panel = panel_from_candles(candles, COSTS)
    trades = trend_trades(history, panel, ("BTC/USDT",), ExecutionConfig(costs=COSTS))
    assert list(trades.columns) == list(TRADE_SCHEMA)
    t = trades.iloc[0]
    signal_day = history[history["uptrend"]]["timestamp"].min()
    assert t["entry_ts"] == signal_day + pd.Timedelta(days=1)  # nunca no fechamento que gerou o sinal
    open_next = float(panel.open.loc[t["entry_ts"], "BTC/USDT"])
    assert t["entry_price"] == pytest.approx(open_next * (1 + 0.0005 + 0.0005))
    assert t["status"] == STATUS_CLOSED and t["exit_reason"] == EXIT_TREND
    exit_signal = history[(history["timestamp"] > signal_day) & ~history["uptrend"]]["timestamp"].min()
    assert t["exit_ts"] == exit_signal + pd.Timedelta(days=1)
    exit_open = float(panel.open.loc[t["exit_ts"], "BTC/USDT"])
    gross = (exit_open * (1 - 0.001)) / (open_next * (1 + 0.001))
    expected = gross * (1 - 0.001) / (1 + 0.001) - 1.0
    assert t["return_pct"] == pytest.approx(expected * 100.0, rel=1e-9)  # líquido de taxa, spread e slippage


def test_performance_uses_the_same_premises_for_every_strategy() -> None:
    candles = _with_gap_opens(make_candles({"BTC/USDT": ramp(50, 150, 500), "ETH/USDT": ramp(10, 30, 500)},
                                           "2026-06-30", quote_volume=1e9))
    history = classify_history(candles, NO_FNG)
    panel = panel_from_candles(candles, COSTS)
    periods = {"TESTE": (pd.Timestamp("2025-06-01", tz="UTC"), pd.Timestamp("2026-06-30", tz="UTC"))}
    cfg = ExecutionConfig(costs=COSTS, rebalance_band=0.05)
    perf = performance_summary(history, panel, {"PRINCIPAIS": ("BTC/USDT", "ETH/USDT")}, periods, cfg)
    assert list(perf.columns) == list(PERFORMANCE_SCHEMA)
    assert set(perf["strategy"]) == {"TENDENCIA", "COMPRAR_E_SEGURAR", "PANICO"}
    rows = perf.set_index("strategy")
    # em alta contínua tendência e comprar e segurar ficam comprados o tempo todo: mesmo resultado
    assert rows.loc["TENDENCIA", "total_return_pct"] == pytest.approx(rows.loc["COMPRAR_E_SEGURAR", "total_return_pct"])
    assert rows.loc["PANICO", "invested_pct"] == 0.0  # sem Fear & Greed o pânico nunca dispara


def test_point_in_time_eligibility_delays_investing() -> None:
    candles = _with_gap_opens(make_candles({"BTC/USDT": ramp(50, 150, 500)}, "2026-06-30", quote_volume=1e9))
    history = classify_history(candles, NO_FNG)
    panel = panel_from_candles(candles, COSTS)
    periods = {"P": (pd.Timestamp(candles["timestamp"].min()), pd.Timestamp("2026-06-30", tz="UTC"))}
    cfg = ExecutionConfig(costs=COSTS)
    free = performance_summary(history, panel, {"X": ("BTC/USDT",)}, periods, cfg)
    late = pd.DataFrame({"BTC/USDT": panel.close.index >= pd.Timestamp("2026-01-01", tz="UTC")}, index=panel.close.index)
    pit = performance_summary(history, panel, {"X": ("BTC/USDT",)}, periods, cfg, eligible=late)
    hold = lambda p: float(p.set_index("strategy").loc["COMPRAR_E_SEGURAR", "invested_pct"])  # noqa: E731
    assert hold(pit) < hold(free)  # sem elegibilidade, nada de compra antes de 2026
