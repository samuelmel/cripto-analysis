"""Candles sintéticos para os testes."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def make_candles(
    closes: dict[str, Sequence[float]],
    end: str | pd.Timestamp = "2026-06-30",
    *,
    source: str = "binance",
    quote_volume: float = 5_000_000.0,
) -> pd.DataFrame:
    """Candles diários no formato padronizado; o último candle de cada moeda é o dia `end`."""
    last = pd.Timestamp(end, tz="UTC") if not isinstance(end, pd.Timestamp) else end
    frames = []
    for symbol, values in closes.items():
        days = pd.date_range(end=last, periods=len(values), freq="D", tz="UTC")
        close = pd.Series(list(values), dtype="float64")
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": days,
                    "source": source,
                    "symbol": symbol,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                    "quote_volume": quote_volume,
                    "trades": 10,
                }
            ).astype({"source": "string", "symbol": "string", "trades": "Int64"})
        )
    return pd.concat(frames, ignore_index=True)


def ramp(start: float, stop: float, n: int) -> list[float]:
    """Linha reta de `start` a `stop` com `n` pontos."""
    return [start + (stop - start) * i / (n - 1) for i in range(n)]
