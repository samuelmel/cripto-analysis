"""Fundo confirmado por 2 candles: sinal sem olhar o futuro, sem sobreposição, custos e inferência."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.transformers.bottom_confirmation import (
    BottomRule,
    STATUS_FEW,
    all_trades,
    bias_summary,
    block_bootstrap_mean,
    bottom_signal_days,
    coin_trades,
    evaluate,
)

START = pd.Timestamp("2020-01-01", tz="UTC")


def frame(close: list[float], open_: list[float] | None = None, symbol: str = "AAA/USDT") -> pd.DataFrame:
    days = pd.date_range(START, periods=len(close), freq="D", tz="UTC")
    return pd.DataFrame({
        "timestamp": days, "symbol": symbol, "close": close,
        "open": open_ if open_ is not None else close,
    })


V_SHAPE = [10.0, 9.0, 8.0, 7.0, 6.0, 7.0, 8.0, 8.5, 8.6, 8.7, 8.8, 8.9, 9.0, 9.1, 9.2]


def test_signal_marks_the_bottom_day_only_when_next_two_closes_rise() -> None:
    close = np.array(V_SHAPE, dtype="float64")
    flags = bottom_signal_days(close, lookback=3)
    assert np.flatnonzero(flags).tolist() == [4]


def test_no_signal_when_confirmation_fails() -> None:
    close = np.array([10.0, 9.0, 8.0, 7.0, 6.0, 7.0, 6.5, 6.4, 6.3], dtype="float64")
    assert not bottom_signal_days(close, lookback=3).any()


def test_signal_never_uses_data_after_t_plus_2() -> None:
    base = np.array(V_SHAPE, dtype="float64")
    changed = base.copy()
    changed[7:] = 1.0  # tudo depois de t+2 (t=4, t+2=6) muda
    assert bottom_signal_days(base, 3)[4] == bottom_signal_days(changed, 3)[4]


def test_honest_entry_is_open_of_t_plus_3_and_biased_is_close_of_t() -> None:
    close = V_SHAPE
    open_ = [c * 1.0 for c in V_SHAPE]
    open_[7] = 8.0  # abertura de t+3 (t=4)
    open_[7 + 2] = 10.0  # saída: abertura de t+3+hold (hold=2)
    trades = coin_trades(frame(close, open_), BottomRule(3, 2), cost=0.0)
    row = trades.iloc[0]
    assert row["entry_date"] == START + pd.Timedelta(days=7)
    assert row["exit_date"] == START + pd.Timedelta(days=9)
    assert np.isclose(row["ret_honest"], 10.0 / 8.0 - 1.0)
    assert np.isclose(row["ret_biased"], 10.0 / 6.0 - 1.0)
    assert row["ret_biased"] > row["ret_honest"]


def test_round_trip_cost_is_subtracted() -> None:
    free = coin_trades(frame(V_SHAPE), BottomRule(3, 2), cost=0.0).iloc[0]
    paid = coin_trades(frame(V_SHAPE), BottomRule(3, 2), cost=0.002).iloc[0]
    assert np.isclose(free["ret_honest"] - paid["ret_honest"], 0.002)
    assert np.isclose(free["ret_biased"] - paid["ret_biased"], 0.002)


def test_trades_do_not_overlap() -> None:
    close = V_SHAPE + [5.0, 4.0, 3.0, 2.0, 3.0, 4.0, 5.0, 5.5, 5.6, 5.7]
    trades = coin_trades(frame(close), BottomRule(3, 10), cost=0.0)
    entries = trades["entry_date"].tolist()
    exits = trades["exit_date"].tolist()
    assert all(entries[i + 1] > exits[i] for i in range(len(entries) - 1))


def test_trade_without_exit_candle_is_dropped() -> None:
    assert coin_trades(frame(V_SHAPE), BottomRule(3, 20), cost=0.0).empty


def test_random_baseline_is_the_mean_of_all_entries_in_the_period() -> None:
    close = V_SHAPE
    trades = coin_trades(frame(close), BottomRule(3, 2), cost=0.0)
    arr = np.array(close)
    expected = float(np.mean(arr[2:] / arr[:-2] - 1.0))
    assert np.isclose(trades["ret_random"].iloc[0], expected)


def test_block_bootstrap_is_deterministic_and_centered() -> None:
    rng = np.random.default_rng(3)
    values = rng.normal(0.02, 0.05, 600)
    days = np.arange(600, dtype="int64")
    a = block_bootstrap_mean(values, days, resamples=500, seed=7)
    b = block_bootstrap_mean(values, days, resamples=500, seed=7)
    assert a == b
    mean, low, high, p = a
    assert low < mean < high
    assert p < 0.05


def test_block_bootstrap_of_noise_does_not_reject() -> None:
    rng = np.random.default_rng(5)
    values = rng.normal(0.0, 0.05, 600)
    _, low, high, p = block_bootstrap_mean(values, np.arange(600, dtype="int64"), resamples=500, seed=7)
    assert low < 0 < high
    assert p > 0.05


def make_market(n_coins: int = 4, days: int = 900, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts = []
    for i in range(n_coins):
        close = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.03, days)))
        opens = np.r_[close[0], close[:-1]]
        parts.append(frame(list(close), list(opens), f"C{i}/USDT"))
    return pd.concat(parts, ignore_index=True)


def test_evaluate_random_walk_is_not_demonstrated_and_bias_is_larger() -> None:
    market = make_market()
    trades = all_trades(market, [BottomRule(10, 5)], split=pd.Timestamp("2021-06-01", tz="UTC"))
    table = evaluate(trades, resamples=300)
    honest_dev = table[table["entry"].eq("HONESTA") & table["period"].eq("DESENVOLVIMENTO")]
    assert not honest_dev.empty
    assert (honest_dev["status"] != "FUNCIONA").all()
    summary = bias_summary(trades, 5, 10)
    assert summary["mean_return"].iloc[0] > summary["mean_return"].iloc[1]


def test_evaluate_flags_insufficient_data() -> None:
    market = make_market(n_coins=1, days=200)
    trades = all_trades(market, [BottomRule(10, 5)], split=pd.Timestamp("2021-06-01", tz="UTC"))
    table = evaluate(trades, resamples=200)
    honest_dev = table[table["entry"].eq("HONESTA") & table["period"].eq("DESENVOLVIMENTO")]
    assert (honest_dev["status"] == STATUS_FEW).all()


def test_all_trades_empty_market() -> None:
    empty = pd.DataFrame({"timestamp": pd.to_datetime([], utc=True), "symbol": [], "close": [], "open": []})
    assert all_trades(empty).empty
