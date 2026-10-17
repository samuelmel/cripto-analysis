"""Regras de saída: queda de 20%, perda da SMA 200, mercado, trailing, estados e critério de adoção do trailing."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.exit_rules import (
    EXIT_MARKET,
    EXIT_OPEN,
    EXIT_STOP,
    EXIT_TRAILING,
    EXIT_TREND,
    STATE_HOLD,
    STATE_SELL,
    STATE_WATCH,
    ExitParams,
    adopted_trailing,
    compare_trailing,
    holdout_vetoes,
    paired_diff_stats,
    position_state,
    rule_report,
    simulate_trades,
)
from src.transformers.signal_validation import Prepared

IDX = pd.date_range("2024-01-01", periods=300, freq="D", tz="UTC")
SIGNAL = 50  # dia do sinal; entrada no fechamento de 51


def prep_for(path: list[float], sma: float = 50.0, btc: float = 100.0, btc_sma: float = 80.0, cost: float = 0.0) -> Prepared:
    """Uma moeda A com o caminho de preços `path` (a partir do dia 51) e o BTC parado. Sinal no dia 50."""
    price = np.full(len(IDX), 100.0)
    price[SIGNAL + 1: SIGNAL + 1 + len(path)] = path
    price[SIGNAL + 1 + len(path):] = path[-1]
    priced = pd.DataFrame({"A/USDT": price, "BTC/USDT": np.full(len(IDX), btc)}, index=IDX)
    sma_df = pd.DataFrame({"A/USDT": np.full(len(IDX), sma), "BTC/USDT": np.full(len(IDX), btc_sma)}, index=IDX)
    events = pd.DataFrame(False, index=IDX, columns=priced.columns)
    events.iloc[SIGNAL, 0] = True
    last = pd.Series(IDX[-1], index=priced.columns)
    return Prepared(events, events.copy(), {}, priced, sma_df, pd.DataFrame(cost, index=IDX, columns=priced.columns), last)


def run(prep: Prepared, params: ExitParams) -> pd.Series:
    trades = simulate_trades(prep, params, entries_from=None, entries_to=IDX[-1], data_end=IDX[-1])
    assert len(trades) == 1
    return trades.iloc[0]


def test_stop_fires_on_a_20_percent_drop_and_sells_at_the_next_close() -> None:
    t = run(prep_for([100, 90, 79.9, 70, 70]), ExitParams(stop=0.20, trend=False, market=False))
    assert t["reason"] == EXIT_STOP
    assert t["entry_ts"] == IDX[SIGNAL + 1]                      # entra no fechamento seguinte ao sinal
    assert t["exit_ts"] == IDX[SIGNAL + 1 + 3]                   # disparou no fechamento do 3º dia; vende no seguinte
    assert t["net_return"] == pytest.approx(70 / 100 - 1)


def test_exact_20_percent_loss_counts_as_stop() -> None:
    t = run(prep_for([100, 80, 80, 80]), ExitParams(stop=0.20, trend=False, market=False))
    assert t["reason"] == EXIT_STOP


def test_trend_loss_fires_when_the_close_goes_below_the_sma() -> None:
    t = run(prep_for([100, 110, 49, 49, 49], sma=50.0), ExitParams(stop=None, trend=True, market=False))
    assert t["reason"] == EXIT_TREND and t["exit_ts"] == IDX[SIGNAL + 1 + 3]


def test_market_rule_uses_the_btc_sma() -> None:
    quiet = run(prep_for([100, 100, 100], btc=100.0, btc_sma=80.0), ExitParams(stop=None, trend=False, market=True))
    assert quiet["reason"] == EXIT_OPEN and bool(quiet["is_open"])
    down = run(prep_for([100, 100, 100], btc=70.0, btc_sma=80.0), ExitParams(stop=None, trend=False, market=True))
    assert down["reason"] == EXIT_MARKET


def test_trailing_stop_measures_the_fall_from_the_peak() -> None:
    path = [100, 120, 150, 140, 127.5, 127.5]  # topo 150; -15% = 127,5
    t = run(prep_for(path), ExitParams(stop=None, trend=False, market=False, trailing=0.15))
    assert t["reason"] == EXIT_TRAILING and t["peak_return"] == pytest.approx(0.5)
    assert t["exit_ts"] == IDX[SIGNAL + 1 + 5]
    off = run(prep_for(path), ExitParams(stop=None, trend=False, market=False, trailing=None))
    assert off["reason"] == EXIT_OPEN


def test_costs_are_charged_on_both_sides() -> None:
    t = run(prep_for([100, 100, 80, 80], cost=0.01), ExitParams(stop=0.20, trend=False, market=False))
    assert t["net_return"] == pytest.approx((1 - 0.01) ** 2 * 0.8 - 1)


def test_rules_use_no_future_information() -> None:
    """Mudar preços depois do dia de decisão não muda a saída decidida antes."""
    base = prep_for([100, 90, 79, 70, 70, 70])
    changed = prep_for([100, 90, 79, 70, 1000, 1000])
    a, b = run(base, ExitParams(trend=False, market=False)), run(changed, ExitParams(trend=False, market=False))
    assert a["exit_ts"] == b["exit_ts"] and a["net_return"] == b["net_return"]


def test_rule_report_describes_what_happened_after_the_sale() -> None:
    prep = prep_for([100, 90, 79, 70, 60, 60] + [60] * 40)
    trades = simulate_trades(prep, ExitParams(trend=False, market=False), entries_from=None, entries_to=IDX[-1], data_end=IDX[-1])
    rep = rule_report(trades)
    assert rep.loc[0, "rule"] == EXIT_STOP and rep.loc[0, "n"] == 1
    assert rep.loc[0, "mean_post_exit_30d"] == pytest.approx(60 / 70 - 1)  # o preço continuou caindo: a venda evitou perda
    assert rep.loc[0, "share_fell_after"] == 1.0


# --------------------------------------------------------------------------------------------- critério do trailing

def trades_with(returns: list[float], offset: int = 0) -> pd.DataFrame:
    n = len(returns)
    return pd.DataFrame(
        {"symbol": pd.Series([f"C{i}" for i in range(n)], dtype="string"),
         "signal_ts": IDX[offset: offset + n], "net_return": returns, "reason": pd.Series([EXIT_TREND] * n, dtype="string")}
    )


def test_random_trailing_is_not_adopted_and_a_real_improvement_is() -> None:
    rng = np.random.default_rng(4)
    base = rng.normal(0.02, 0.2, 200)
    noise = {x: trades_with(list(base + rng.normal(0.0, 0.05, 200))) for x in (0.10, 0.15, 0.20)}
    grid = compare_trailing(trades_with(list(base)), noise, resamples=500)
    assert adopted_trailing(grid) is None
    better = {x: trades_with(list(base + (0.08 if x == 0.20 else rng.normal(0, 0.05, 200)))) for x in (0.10, 0.15, 0.20)}
    grid = compare_trailing(trades_with(list(base)), better, resamples=500)
    assert adopted_trailing(grid) == 0.20


def test_same_seed_same_interval() -> None:
    d = np.random.default_rng(1).normal(0.01, 0.1, 80)
    assert paired_diff_stats(d, 9, 400) == paired_diff_stats(d, 9, 400)
    assert paired_diff_stats(d, 9, 400) != paired_diff_stats(d, 10, 400)


def test_holdout_can_only_veto() -> None:
    base = trades_with([0.1] * 30)
    worse = trades_with([0.05] * 30)
    better = trades_with([0.2] * 30)
    assert holdout_vetoes(base, worse) is True
    assert holdout_vetoes(base, better) is False
    assert holdout_vetoes(trades_with([0.1] * 5), trades_with([0.0] * 5)) is False  # poucas operações: não revoga


# -------------------------------------------------------------------------------------------------------- estado

def state(closes: list[float], **over: float) -> str:
    args = dict(entry_price=100.0, sma=60.0, btc_close=100.0, btc_sma=80.0)
    args.update(over)
    return position_state(closes_since_entry=closes, params=ExitParams(trailing=None), **args).state  # type: ignore[arg-type]


def test_states_hold_watch_and_sell() -> None:
    assert state([100, 110, 120]) == STATE_HOLD
    assert state([100, 90]) == STATE_WATCH                       # -10%: metade do caminho até o stop
    assert state([100, 79]) == STATE_SELL                         # -21%
    assert state([100, 120, 59], sma=60.0) == STATE_SELL         # perdeu a SMA 200 (também é -41% do topo)
    assert state([100, 120, 130], sma=127.0) == STATE_WATCH      # a 2,4% acima da SMA 200
    assert state([100, 110], btc_close=70.0, btc_sma=80.0) == STATE_SELL
    assert state([100, 110], btc_close=81.0, btc_sma=80.0) == STATE_WATCH
    drawn = position_state(closes_since_entry=[100, 150, 135], entry_price=100.0, sma=60.0, btc_close=100.0, btc_sma=80.0,
                           params=ExitParams(trailing=0.20))
    assert drawn.state == STATE_WATCH and drawn.rule == EXIT_TRAILING  # -10% do topo = metade de 20%


def test_state_names_the_rule_that_fired() -> None:
    s = position_state(closes_since_entry=[100, 75], entry_price=100.0, sma=60.0, btc_close=100.0, btc_sma=80.0, params=ExitParams())
    assert s.state == STATE_SELL and s.rule == EXIT_STOP and "-25" in s.detail.replace("−", "-")
