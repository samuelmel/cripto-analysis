"""Extratores: resposta incompleta ou inesperada vira ExtractorError, nunca dado silenciosamente errado."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pytest

from src.extractors import BinanceAdapter, CoinGeckoMarketAdapter, ExtractorError, FearGreedAdapter
from src.extractors import binance_adapter, coingecko_adapter, fng_adapter

DAY_MS = 86_400_000
T0 = 1_750_000_000_000 // DAY_MS * DAY_MS


def kline(i: int, close: float = 100.0) -> list[Any]:
    return [T0 + i * DAY_MS, "1", "2", "0.5", str(close), "10", T0 + (i + 1) * DAY_MS - 1, "1000", 5, "0", "0", "0"]


def end_after(n: int) -> Any:
    return pd.Timestamp(T0 + n * DAY_MS, unit="ms", tz="UTC").to_pydatetime()


def test_binance_ok_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binance_adapter, "get_json", lambda *a, **k: [kline(0), kline(1), kline(2)])
    frame = BinanceAdapter(["BTC/USDT"]).extract(pd.Timestamp(T0, unit="ms", tz="UTC").to_pydatetime(), end_after(3))
    assert frame["symbol"].unique().tolist() == ["BTC/USDT"]
    assert frame["source"].unique().tolist() == ["binance"]
    assert len(frame) == 3


def test_binance_error_payload_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binance_adapter, "get_json", lambda *a, **k: {"code": -1121, "msg": "Invalid symbol."})
    with pytest.raises(ExtractorError, match="inesperada"):
        BinanceAdapter(["XXX/USDT"]).extract(pd.Timestamp(T0, unit="ms", tz="UTC").to_pydatetime(), end_after(3))


def test_binance_incomplete_candle_is_rejected() -> None:
    with pytest.raises(ExtractorError, match="incompleto"):
        BinanceAdapter(["BTC/USDT"]).to_frame({"BTC/USDT": [[T0, "1", "2"]]})


def test_binance_drops_the_still_open_candle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binance_adapter, "get_json", lambda *a, **k: [kline(0), kline(1)])
    frame = BinanceAdapter(["BTC/USDT"]).extract(pd.Timestamp(T0, unit="ms", tz="UTC").to_pydatetime(), end_after(1))
    assert len(frame) == 1  # o candle 1 ainda não fechou em T0 + 1 dia


def test_coingecko_missing_fields_are_rejected() -> None:
    adapter = CoinGeckoMarketAdapter(["bitcoin"])
    raw = [{"id": "bitcoin", "symbol": "btc", "current_price": 1.0, "last_updated": "2026-06-30T00:00:00Z"}]
    with pytest.raises(ExtractorError, match="market_cap"):
        adapter.to_frame(raw)


def test_coingecko_empty_or_wrong_shape_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    for payload in ([], {"status": {"error_code": 429}}):
        monkeypatch.setattr(coingecko_adapter, "get_json", lambda *a, _p=payload, **k: _p)
        with pytest.raises(ExtractorError):
            CoinGeckoMarketAdapter(["bitcoin"]).fetch(None, pd.Timestamp.now(tz="UTC").to_pydatetime())


def test_coingecko_missing_coin_only_warns(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    row = {"id": "bitcoin", "symbol": "btc", "current_price": 1.0, "market_cap": 2.0, "total_volume": 3.0,
           "last_updated": "2026-06-30T00:00:00Z"}
    monkeypatch.setattr(coingecko_adapter, "get_json", lambda *a, **k: [row])
    with caplog.at_level(logging.WARNING):
        frame = CoinGeckoMarketAdapter(["bitcoin", "ethereum"]).extract(None, pd.Timestamp.now(tz="UTC").to_pydatetime())
    assert frame["symbol"].tolist() == ["BTC"]
    assert "ethereum" in caplog.text


def test_coingecko_demo_key_goes_in_header_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(url: str, params: Any = None, headers: Any = None, **kwargs: Any) -> list[Any]:
        seen.update(url=url, params=params, headers=headers, kwargs=kwargs)
        return [{"id": "bitcoin", "symbol": "btc", "current_price": 1.0, "market_cap": 2.0, "total_volume": 3.0,
                 "last_updated": "2026-06-30T00:00:00Z"}]

    monkeypatch.setattr(coingecko_adapter, "get_json", fake)
    CoinGeckoMarketAdapter(["bitcoin"], api_key="K").extract(None, pd.Timestamp.now(tz="UTC").to_pydatetime())
    assert seen["headers"] == {"x-cg-demo-api-key": "K"}
    assert "K" not in str(seen["params"])
    assert seen["kwargs"]["min_interval"] == coingecko_adapter.MIN_INTERVAL


def test_fng_missing_fields_are_rejected() -> None:
    with pytest.raises(ExtractorError, match="value"):
        FearGreedAdapter().to_frame([{"timestamp": "1750000000", "value_classification": "Fear"}])


def test_fng_wrong_shape_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fng_adapter, "get_json", lambda *a, **k: {"name": "Fear and Greed", "metadata": {"error": "limit"}})
    with pytest.raises(ExtractorError, match="inesperada"):
        FearGreedAdapter().fetch(None, pd.Timestamp.now(tz="UTC").to_pydatetime())


def test_fng_unparseable_timestamp_is_rejected() -> None:
    adapter = FearGreedAdapter()
    frame = adapter.to_frame([{"timestamp": "ontem", "value": "40", "value_classification": "Fear"}])
    with pytest.raises(ExtractorError, match="nulas"):
        adapter.standardize(frame)
