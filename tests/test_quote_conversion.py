"""Pares em BTC convertidos para USDT e emendados antes do primeiro candle em USDT."""

from __future__ import annotations

import pandas as pd
import pytest

from src.transformers.quote_conversion import SOURCE_CONVERTED, splice, to_usdt

UTC = "UTC"


def _c(symbol: str, days: list[str], o: list[float], c: list[float], h: list[float] | None = None,
       lo: list[float] | None = None, qv: list[float] | None = None) -> pd.DataFrame:
    n = len(days)
    return pd.DataFrame({
        "symbol": symbol, "timestamp": pd.to_datetime(days, utc=True), "source": "binance",
        "open": o, "high": h or [max(a, b) for a, b in zip(o, c, strict=True)],
        "low": lo or [min(a, b) for a, b in zip(o, c, strict=True)], "close": c,
        "volume": [1.0] * n, "quote_volume": qv or [2.0] * n,
    })


def test_conversion_uses_btc_usdt_of_the_same_day() -> None:
    btc = _c("BTC/USDT", ["2018-01-01", "2018-01-02"], [10_000, 11_000], [11_000, 12_000])
    alt = _c("XYZ/BTC", ["2018-01-01", "2018-01-02", "2018-01-03"], [0.001, 0.002, 0.003], [0.002, 0.003, 0.004],
             h=[0.0025, 0.0031, 0.005], lo=[0.0009, 0.0019, 0.002], qv=[5.0, 6.0, 7.0])
    out = to_usdt(alt, btc)
    assert out["symbol"].eq("XYZ/USDT").all() and out["source"].eq(SOURCE_CONVERTED).all()
    assert len(out) == 2                                           # 3/1 sem BTCUSDT: não convertido
    r = out.iloc[0]
    assert r["open"] == pytest.approx(0.001 * 10_000) and r["close"] == pytest.approx(0.002 * 11_000)
    assert r["high"] == pytest.approx(0.0025 * 11_000) and r["quote_volume"] == pytest.approx(5.0 * 11_000)
    assert (out["high"] >= out[["open", "close"]].max(axis=1)).all() and (out["low"] <= out[["open", "close"]].min(axis=1)).all()


def test_splice_keeps_usdt_and_only_adds_converted_days_before_it() -> None:
    usdt = _c("XYZ/USDT", ["2018-01-03", "2018-01-04"], [30.0, 31.0], [31.0, 32.0])
    conv = _c("XYZ/USDT", ["2018-01-01", "2018-01-02", "2018-01-03"], [10.0, 20.0, 99.0], [20.0, 30.0, 99.0]).assign(source=SOURCE_CONVERTED)
    only_btc = _c("OLD/USDT", ["2018-01-01"], [1.0], [2.0]).assign(source=SOURCE_CONVERTED)
    out = splice(usdt, pd.concat([conv, only_btc], ignore_index=True))
    xyz = out[out["symbol"].eq("XYZ/USDT")].set_index("timestamp")
    assert len(xyz) == 4
    assert xyz.loc[pd.Timestamp("2018-01-03", tz=UTC), "close"] == 31.0            # o USDT vence no dia em comum
    assert xyz.loc[pd.Timestamp("2018-01-01", tz=UTC), "source"] == SOURCE_CONVERTED
    assert out["symbol"].eq("OLD/USDT").sum() == 1                                  # moeda que só teve par em BTC
    assert splice(usdt, conv.iloc[0:0]).equals(usdt)
