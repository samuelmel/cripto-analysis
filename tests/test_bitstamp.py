"""Adaptador Bitstamp (sem rede): paginação, candle aberto descartado, contrato do formato padronizado."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest

from src.extractors import ExtractorError, bitstamp_adapter
from src.extractors.bitstamp_adapter import BitstampAdapter

DAY = 86_400
T0 = int(datetime(2011, 8, 18, tzinfo=timezone.utc).timestamp())


def candle(i: int) -> dict[str, str]:
    return {"timestamp": str(T0 + i * DAY), "open": str(10 + i), "high": str(11 + i), "low": str(9 + i),
            "close": str(10.5 + i), "volume": "2"}


def test_paginates_and_drops_the_open_candle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake(url: str, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        calls.append(params)
        first = (int(params["start"]) - T0) // DAY
        return {"data": {"pair": "BTC/USD", "ohlc": [candle(i) for i in range(first, min(first + 1000, 2500))]}}

    monkeypatch.setattr(bitstamp_adapter, "get_json", fake)
    end = datetime.fromtimestamp(T0 + 2400 * DAY + 3600, tz=timezone.utc)  # 1 h depois da abertura do dia 2400
    df = BitstampAdapter(["BTC/USD"]).extract(None, end)
    assert len(calls) == 3                                   # 1000 + 1000 + 400
    assert len(df) == 2400                                   # o dia 2400 ainda está aberto: fora
    assert df["timestamp"].is_monotonic_increasing and df["source"].eq("bitstamp").all()
    assert df["quote_volume"].iloc[0] == pytest.approx(2 * 10.5)
    assert df["timestamp"].iloc[0] == pd.Timestamp("2011-08-18", tz="UTC")


def test_rejects_unexpected_payload_and_non_usd_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bitstamp_adapter, "get_json", lambda *a, **k: {"error": "x"})
    with pytest.raises(ExtractorError):
        BitstampAdapter(["BTC/USD"]).extract(None, datetime(2012, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        BitstampAdapter(["BTC/USDT"])


def test_pair_listed_after_2011_is_found_by_skipping_empty_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    listed = 2500  # o par começa 2.500 dias depois do primeiro dia do BTC

    def fake(url: str, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        first = max((int(params["start"]) - T0) // DAY, listed)
        return {"data": {"ohlc": [candle(i) for i in range(first, min(first + 1000, 3000))]}}

    monkeypatch.setattr(bitstamp_adapter, "get_json", fake)
    df = BitstampAdapter(["ETH/USD"]).extract(None, datetime.fromtimestamp(T0 + 3000 * DAY, tz=timezone.utc))
    assert len(df) == 500 and df["timestamp"].iloc[0] == pd.Timestamp(T0 + listed * DAY, unit="s", tz="UTC")
