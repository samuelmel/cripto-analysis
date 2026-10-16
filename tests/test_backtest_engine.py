"""Motor de backtest de referência: execução no candle seguinte, custos, caixa, deslistagem, lacunas e contabilidade."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.transformers.backtest_engine import (
    ORDER_BAND,
    ORDER_EXPIRED,
    ORDER_FILLED,
    ORDER_NOT_ELIGIBLE,
    ORDER_PARTIAL,
    ORDER_SUPERSEDED,
    SIDE_BUY,
    SIDE_SELL,
    SIDE_WRITE_OFF,
    ExecutionConfig,
    MarketPanel,
    panel_from_candles,
    reconcile,
    run_backtest,
    summarize,
    total_costs,
)
from src.transformers.costs import CostModel

FREE = ExecutionConfig(costs=CostModel(fee_rate=0.0, slippage=0.0, spread_tiers=((0.0, 0.0),)))
START = pd.Timestamp("2024-01-01", tz="UTC")


def _days(n: int) -> pd.DatetimeIndex:
    return pd.date_range(START, periods=n, freq="D")


def _panel(opens: dict[str, list[float]], closes: dict[str, list[float]], spread: float = 0.0) -> MarketPanel:
    n = len(next(iter(closes.values())))
    idx = _days(n)
    o = pd.DataFrame(opens, index=idx, dtype="float64")
    c = pd.DataFrame(closes, index=idx, dtype="float64")
    return MarketPanel(o, c, pd.DataFrame(spread, index=idx, columns=c.columns))


def _flat(values: list[float]) -> tuple[list[float], list[float]]:
    """Abertura = fechamento anterior (sem gap)."""
    return [values[0], *values[:-1]], values


def _target(day: int, weights: dict[str, float], n: int, cols: list[str]) -> pd.DataFrame:
    t = pd.DataFrame(np.nan, index=_days(n), columns=cols)
    t.iloc[day] = [weights.get(c, 0.0) for c in cols]
    return t.dropna(how="all")


def _ok(result: object) -> None:
    from src.transformers.backtest_engine import BacktestResult

    assert isinstance(result, BacktestResult)
    assert reconcile(result) == []


# ---- execução temporal -----------------------------------------------------------------------------

def test_signal_at_close_d_executes_at_open_d_plus_1_not_at_close_d() -> None:
    # O preço salta de 100 para 150 DURANTE o dia 2. O sinal (calculado no fechamento de 2, já em 150) não pode
    # ganhar esse salto: a compra é feita na abertura do dia 3, a 150.
    closes = [100.0, 100.0, 150.0, 150.0, 150.0]
    opens = [100.0, 100.0, 100.0, 150.0, 150.0]
    result = run_backtest(_panel({"A": opens}, {"A": closes}), _target(2, {"A": 1.0}, 5, ["A"]), cfg=FREE)
    buy = result.trades.iloc[0]
    assert buy["executed_at"] == _days(5)[3] and buy["reference_price"] == 150.0
    assert result.equity.iloc[-1] == pytest.approx(1.0)  # nenhum ganho do salto que gerou o sinal
    _ok(result)


def test_return_between_open_and_close_of_execution_day_is_earned() -> None:
    opens, closes = [100.0, 100.0, 110.0, 121.0], [100.0, 110.0, 121.0, 133.1]
    result = run_backtest(_panel({"A": opens}, {"A": closes}), _target(0, {"A": 1.0}, 4, ["A"]), cfg=FREE)
    # comprado na abertura do dia 1 (100); a cada fechamento +10%
    assert result.equity.round(10).tolist() == [1.0, 1.1, 1.21, 1.331]
    assert result.returns.iloc[1:].round(10).tolist() == [0.1, 0.1, 0.1]
    _ok(result)


def test_constant_price_without_costs_keeps_equity() -> None:
    o, c = _flat([50.0] * 10)
    result = run_backtest(_panel({"A": o}, {"A": c}), _target(0, {"A": 1.0}, 10, ["A"]), cfg=FREE)
    assert np.allclose(result.equity, 1.0)
    assert result.exposure.iloc[-1] == pytest.approx(1.0)
    _ok(result)


def test_prices_after_day_k_do_not_change_results_up_to_k() -> None:
    o, c = _flat(list(np.linspace(100, 200, 30)))
    targets = pd.DataFrame({"A": [1.0, 0.0, 1.0, 0.5] * 7 + [1.0, 1.0]}, index=_days(30))
    base = run_backtest(_panel({"A": o}, {"A": c}), targets, cfg=ExecutionConfig())
    o2, c2 = o.copy(), c.copy()
    for i in range(16, 30):
        o2[i] *= 3.0
        c2[i] *= 0.2
    changed = run_backtest(_panel({"A": o2}, {"A": c2}), targets, cfg=ExecutionConfig())
    pd.testing.assert_series_equal(base.equity.iloc[:16], changed.equity.iloc[:16])
    _ok(base)
    _ok(changed)


def test_consecutive_signals_each_execute_on_the_next_open() -> None:
    o, c = _flat([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    targets = pd.DataFrame({"A": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]}, index=_days(6))
    result = run_backtest(_panel({"A": o}, {"A": c}), targets, cfg=FREE)
    sides = result.trades[["executed_at", "side"]]
    assert sides["side"].tolist() == [SIDE_BUY, SIDE_SELL, SIDE_BUY, SIDE_SELL, SIDE_BUY]
    assert sides["executed_at"].tolist() == list(_days(6)[1:])  # sempre o dia seguinte à decisão
    _ok(result)


def test_decision_before_the_window_executes_at_the_first_open_of_the_window() -> None:
    o, c = _flat([10.0] * 10)
    targets = _target(2, {"A": 1.0}, 10, ["A"])
    result = run_backtest(_panel({"A": o}, {"A": c}), targets, cfg=FREE, start=_days(10)[5])
    assert result.trades["executed_at"].iloc[0] == _days(10)[5]
    _ok(result)


# ---- custos --------------------------------------------------------------------------------------------

def test_known_round_trip_cost_matches_the_formula() -> None:
    fee, half, slip = 0.001, 0.0005, 0.0005
    cfg = ExecutionConfig(costs=CostModel(fee_rate=fee, slippage=slip, spread_tiers=((0.0, half),)))
    o, c = _flat([100.0] * 6)
    targets = pd.DataFrame({"A": [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]}, index=_days(6))
    result = run_backtest(_panel({"A": o}, {"A": c}, spread=half), targets, cfg=cfg)
    expected = (1 - half - slip) * (1 - fee) / ((1 + half + slip) * (1 + fee))
    assert result.equity.iloc[-1] == pytest.approx(expected, rel=1e-12)
    costs = total_costs(result)
    assert costs["total"] == pytest.approx(1.0 - expected, rel=1e-9)  # a perda é exatamente o custo
    assert costs["fee"] > 0 and costs["spread"] > 0 and costs["slippage"] > 0
    _ok(result)


def test_no_cost_is_charged_when_nothing_is_traded() -> None:
    o, c = _flat([100.0] * 5)
    result = run_backtest(_panel({"A": o}, {"A": c}, spread=0.01), pd.DataFrame(columns=["A"], dtype="float64"))
    assert result.trades.empty and np.allclose(result.equity, 1.0)
    assert total_costs(result)["total"] == 0.0


def test_band_skips_small_rebalances() -> None:
    o, c = _flat([100.0, 110.0, 120.0, 130.0, 140.0])
    targets = pd.DataFrame({"A": [0.5] * 5, "B": [0.5] * 5}, index=_days(5))
    panel = _panel({"A": o, "B": [100.0] * 5}, {"A": c, "B": [100.0] * 5})
    banded = run_backtest(panel, targets, cfg=ExecutionConfig(costs=FREE.costs, rebalance_band=0.10))
    daily = run_backtest(panel, targets, cfg=FREE)
    assert len(banded.trades) == 2 and (banded.orders["status"] == ORDER_BAND).any()
    assert len(daily.trades) > len(banded.trades)  # sem banda, o desvio vira operação (e custo)
    _ok(banded)
    _ok(daily)


# ---- dados ausentes, deslistagem, lacunas ---------------------------------------------------------------

def test_missing_candle_delays_the_order_to_the_next_valid_open() -> None:
    o, c = _flat([100.0] * 6)
    o[1], c[1] = math.nan, math.nan  # sem candle no dia seguinte à decisão
    result = run_backtest(_panel({"A": o}, {"A": c}), _target(0, {"A": 1.0}, 6, ["A"]), cfg=FREE)
    order = result.orders.iloc[0]
    assert order["status"] == ORDER_FILLED and order["executed_at"] == _days(6)[2] and order["delay_days"] == 1
    _ok(result)


def test_order_without_a_valid_price_expires_and_is_never_executed() -> None:
    o, c = _flat([100.0] * 10)
    for i in range(1, 7):
        o[i] = math.nan  # abertura inválida por 6 dias (o fechamento existe)
    cfg = ExecutionConfig(costs=FREE.costs, max_order_delay_days=2)
    result = run_backtest(_panel({"A": o}, {"A": c}), _target(0, {"A": 1.0}, 10, ["A"]), cfg=cfg)
    assert result.orders["status"].tolist() == [ORDER_EXPIRED]
    assert result.trades.empty and np.allclose(result.equity, 1.0)
    _ok(result)


def test_delisted_asset_is_written_off_and_cash_stays_consistent() -> None:
    n = 20
    o, c = _flat([100.0] * n)
    for i in range(8, n):
        o[i], c[i] = math.nan, math.nan  # parou de negociar no dia 8
    cfg = ExecutionConfig(costs=FREE.costs, delist_after_days=5, delist_recovery=0.0)
    result = run_backtest(_panel({"A": o}, {"A": c}), _target(0, {"A": 1.0}, n, ["A"]), cfg=cfg)
    off = result.trades[result.trades["side"].eq(SIDE_WRITE_OFF)].iloc[0]
    assert off["executed_at"] == _days(n)[7 + 6]  # último candle no dia 7; baixa quando passa de 5 dias sem candle
    assert result.equity.iloc[:13].round(12).eq(1.0).all()  # até a baixa vale o último fechamento conhecido
    assert result.equity.iloc[-1] == 0.0 and result.units.iloc[-1, 0] == 0.0
    _ok(result)
    partial = run_backtest(_panel({"A": o}, {"A": c}), _target(0, {"A": 1.0}, n, ["A"]),
                           cfg=ExecutionConfig(costs=FREE.costs, delist_after_days=5, delist_recovery=0.25))
    assert partial.equity.iloc[-1] == pytest.approx(0.25)
    _ok(partial)


def test_no_return_crosses_a_gap_between_episodes() -> None:
    # Caso LUNA: 80 -> 18 dias sem candle -> volta a 8 como outro ativo sob o mesmo símbolo.
    closes = [80.0] * 5 + [math.nan] * 18 + [8.0] * 5
    opens = [80.0] * 5 + [math.nan] * 18 + [8.0] * 5
    targets = pd.DataFrame({"A": [1.0] * 28}, index=_days(28))  # a estratégia "quer" ficar comprada o tempo todo
    cfg = ExecutionConfig(costs=FREE.costs, delist_after_days=7, delist_recovery=0.0)
    result = run_backtest(_panel({"A": opens}, {"A": closes}), targets, cfg=cfg)
    write_off = result.trades[result.trades["side"].eq(SIDE_WRITE_OFF)]
    assert len(write_off) == 1 and write_off["executed_at"].iloc[0] < _days(28)[23]
    rebuy = result.trades[result.trades["side"].eq(SIDE_BUY) & result.trades["executed_at"].ge(_days(28)[23])]
    assert rebuy.empty  # patrimônio zerado: nada a comprar; o "retorno" de 80 -> 8 nunca aparece como ganho/perda contínua
    assert result.equity.iloc[-1] == 0.0
    _ok(result)


def test_insufficient_cash_scales_buys_and_never_goes_negative() -> None:
    # B não pode ser vendida (sem abertura) quando a decisão manda trocar B por A: a compra de A cabe só no caixa.
    oa, ca = _flat([100.0] * 6)
    ob, cb = _flat([100.0] * 6)
    ob[2] = math.nan
    targets = pd.DataFrame({"A": [0.0, 1.0, 1.0, 1.0, 1.0, 1.0], "B": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]}, index=_days(6))
    result = run_backtest(_panel({"A": oa, "B": ob}, {"A": ca, "B": cb}), targets, cfg=FREE)
    partial = result.orders[result.orders["status"].eq(ORDER_PARTIAL)]
    assert not partial.empty and (partial["fill_ratio"] < 1).all()
    assert (result.cash >= 0).all() and (result.exposure <= 1 + 1e-12).all()
    _ok(result)


def test_no_cash_means_no_buy_record() -> None:
    # Todo o patrimônio está em B, que não abre no dia em que a decisão manda comprar A: nada a comprar.
    oa, ca = _flat([100.0] * 5)
    ob, cb = _flat([100.0] * 5)
    ob[2] = math.nan
    targets = pd.DataFrame({"A": [0.0, 1.0, 0.0, 0.0, 0.0], "B": [1.0, 0.0, 1.0, 1.0, 1.0]}, index=_days(5))
    result = run_backtest(_panel({"A": oa, "B": ob}, {"A": ca, "B": cb}), targets, cfg=FREE)
    assert not (result.trades["side"].eq(SIDE_BUY) & result.trades["symbol"].eq("A")).any()
    assert (result.trades["quantity"] > 0).all()
    _ok(result)


def test_ineligible_asset_is_not_bought_and_existing_position_is_sold() -> None:
    o, c = _flat([100.0] * 6)
    targets = pd.DataFrame({"A": [1.0] * 6}, index=_days(6))
    eligible = pd.DataFrame({"A": [True, True, False, False, False, False]}, index=_days(6))
    result = run_backtest(_panel({"A": o}, {"A": c}), targets, eligible=eligible, cfg=FREE)
    assert result.trades["side"].tolist() == [SIDE_BUY, SIDE_SELL]
    assert result.trades["executed_at"].iloc[1] == _days(6)[3]  # decidido fora do universo em 2, vendido na abertura de 3
    # decisões em 2, 3 e 4; a do último dia (5) não tem candle seguinte dentro da janela e não é carregada
    assert (result.orders["status"] == ORDER_NOT_ELIGIBLE).sum() == 3
    _ok(result)


def test_a_newer_decision_supersedes_a_pending_order() -> None:
    o, c = _flat([100.0] * 6)
    o[1] = math.nan
    targets = pd.DataFrame({"A": [1.0, 0.5, 0.5, 0.5, 0.5, 0.5]}, index=_days(6))
    result = run_backtest(_panel({"A": o}, {"A": c}), targets, cfg=FREE)
    assert result.orders["status"].iloc[0] == ORDER_SUPERSEDED
    assert result.exposure.iloc[-1] == pytest.approx(0.5)
    _ok(result)


def test_correlated_assets_behave_like_one() -> None:
    path = list(np.cumprod([1.0] + [1.01, 0.98, 1.03, 0.97, 1.02] * 4) * 100)
    o, c = _flat(path)
    n = len(path)
    one = run_backtest(_panel({"A": o}, {"A": c}), pd.DataFrame({"A": [1.0] * n}, index=_days(n)), cfg=FREE)
    two = run_backtest(_panel({"A": o, "B": o}, {"A": c, "B": c}),
                       pd.DataFrame({"A": [0.5] * n, "B": [0.5] * n}, index=_days(n)), cfg=FREE)
    pd.testing.assert_series_equal(one.equity, two.equity)
    _ok(two)


def test_invalid_targets_are_rejected() -> None:
    o, c = _flat([1.0] * 3)
    panel = _panel({"A": o, "B": o}, {"A": c, "B": c})
    with pytest.raises(ValueError, match="descoberto"):
        run_backtest(panel, pd.DataFrame({"A": [-0.1, 0, 0], "B": [0, 0, 0]}, index=_days(3)))
    with pytest.raises(ValueError, match="alavancagem"):
        run_backtest(panel, pd.DataFrame({"A": [0.7, 0, 0], "B": [0.6, 0, 0]}, index=_days(3)))


def test_reconcile_detects_inconsistent_books() -> None:
    o, c = _flat([100.0, 105.0, 103.0, 108.0])
    result = run_backtest(_panel({"A": o}, {"A": c}), _target(0, {"A": 1.0}, 4, ["A"]))
    assert reconcile(result) == []
    tampered = type(result)(**{**result.__dict__, "cash": result.cash + 0.01})
    assert reconcile(tampered)


def test_panel_from_candles_spreads_use_only_past_volume() -> None:
    days = _days(40)
    vol = [1e9] * 30 + [1.0] * 10  # a liquidez some no dia 30
    candles = pd.DataFrame({"symbol": "A", "timestamp": days, "open": 1.0, "close": 1.0, "quote_volume": vol})
    model = CostModel(spread_tiers=((5e8, 0.0002), (0.0, 0.01)))
    panel = panel_from_candles(candles, model, volume_window=3)
    assert panel.half_spread["A"].iloc[30] == 0.0002  # no dia 30 só se conhece o volume até o dia 29
    assert panel.half_spread["A"].iloc[33] == 0.01


def test_summary_counts_entries_turnover_and_costs() -> None:
    o, c = _flat([100.0] * 8)
    targets = pd.DataFrame({"A": [1, 0, 1, 0, 1, 0, 0, 0]}, index=_days(8), dtype="float64")
    result = run_backtest(_panel({"A": o}, {"A": c}), targets)
    m = summarize(result)
    assert m["n_trades"] == 3
    assert float(m["cost_pct"]) > 0 and float(m["turnover_per_year"]) > 0
    assert float(m["invested"]) < 100.0
