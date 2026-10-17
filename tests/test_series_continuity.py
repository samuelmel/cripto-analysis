"""Continuidade das séries: lacuna e salto para cima dividem o par; queda grande e falha de 1 candle não."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.transformers.series_continuity import (
    REASON_BOTH,
    REASON_GAP,
    REASON_JUMP,
    segment_symbol,
    split_discontinuities,
)


def frame(symbol: str, closes: list[float], start: str = "2022-01-01", drop: tuple[int, ...] = ()) -> pd.DataFrame:
    days = pd.date_range(start, periods=len(closes), freq="D", tz="UTC")
    out = pd.DataFrame({"timestamp": days, "symbol": symbol, "close": closes, "volume": 1.0})
    return out.drop(index=list(drop)).reset_index(drop=True)


def test_gap_of_two_missing_candles_splits_the_pair() -> None:
    raw = frame("AAA/USDT", [1.0] * 10, drop=(4, 5))  # faltam 2 candles seguidos (gap de 3 dias)
    out, report = split_discontinuities(raw)
    assert set(out["symbol"]) == {"AAA/USDT", "AAA#2/USDT"}
    assert list(report["reason"]) == [REASON_GAP] and int(report["gap_days"].iloc[0]) == 3
    assert (out.loc[out["symbol"].eq("AAA#2/USDT"), "timestamp"] > pd.Timestamp("2022-01-05", tz="UTC")).all()


def test_one_missing_candle_is_tolerated() -> None:
    out, report = split_discontinuities(frame("AAA/USDT", [1.0] * 10, drop=(4,)))
    assert report.empty and set(out["symbol"]) == {"AAA/USDT"}


def test_jump_up_above_ten_times_splits_and_ten_times_exactly_does_not() -> None:
    _, rep = split_discontinuities(frame("AAA/USDT", [1.0, 1.0, 10.01, 10.0]))
    assert list(rep["reason"]) == [REASON_JUMP]
    _, rep = split_discontinuities(frame("AAA/USDT", [1.0, 1.0, 10.0, 10.0]))
    assert rep.empty


def test_huge_drop_is_not_a_break_so_the_crash_stays_in_the_series() -> None:
    out, report = split_discontinuities(frame("LUNA/USDT", [80.0, 17.0, 1.0, 0.0003, 0.00005]))
    assert report.empty and set(out["symbol"]) == {"LUNA/USDT"}


def test_luna_like_gap_plus_relaunch_is_one_break_with_both_reasons() -> None:
    raw = frame("LUNA/USDT", [0.0003, 0.0003, 0.0003, 5.0], drop=(1, 2))
    out, report = split_discontinuities(raw)
    assert list(report["reason"]) == [REASON_BOTH]
    assert set(out["symbol"]) == {"LUNA/USDT", "LUNA#2/USDT"}


def test_other_pairs_and_input_are_untouched() -> None:
    a = frame("AAA/USDT", [1.0, 2.0, 3.0])
    b = frame("BBB/USDT", [1.0, 1.0, 1.0, 50.0])
    raw = pd.concat([a, b], ignore_index=True)
    before = raw.copy()
    out, _ = split_discontinuities(raw)
    pd.testing.assert_frame_equal(raw, before)
    assert (out[out["symbol"].eq("AAA/USDT")]["close"].to_numpy() == [1.0, 2.0, 3.0]).all()
    assert len(out) == len(raw) and np.isclose(out["close"].sum(), raw["close"].sum())


def test_segment_names() -> None:
    assert segment_symbol("LUNA/USDT", 0) == "LUNA/USDT" and segment_symbol("LUNA/USDT", 2) == "LUNA#3/USDT"
