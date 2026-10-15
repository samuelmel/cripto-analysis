"""Adaptador Binance: OHLCV e volume de pares spot via REST pública (/api/v3/klines).

Para backfill de anos, extract_binance_vision.py (ZIP mensal) segue sendo a via mais barata;
o pipeline diário só precisa das últimas centenas de velas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

import pandas as pd

from .base_extractor import BaseExtractor, ExtractorError
from .http import get_json

DEFAULT_HOST = "https://api.binance.com"
ALLOWED_HOSTS = (DEFAULT_HOST, "https://data-api.binance.vision")
"""api.binance.com é o principal; data-api.binance.vision serve os mesmos dados públicos de mercado e é a
alternativa quando o primeiro recusa o data center (HTTP 451). Só estes hosts são aceitos."""
KLINES_PATH = "/api/v3/klines"
PAGE_LIMIT = 1000
MIN_INTERVAL = 0.2  # s entre chamadas; o limite é por peso/IP (429 traz Retry-After, respeitado em http.get_json)
DEFAULT_LOOKBACK = timedelta(days=250)  # SMA 90 + aquecimento do RSI com folga
TIMEFRAME_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

# Posições do array de kline da Binance.
_FIELDS = {0: "timestamp", 1: "open", 2: "high", 3: "low", 4: "close", 5: "volume", 7: "quote_volume", 8: "trades"}


class BinanceAdapter(BaseExtractor):
    source: ClassVar[str] = "binance"
    value_columns: ClassVar[dict[str, str]] = {
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "float64",        # volume no ativo base
        "quote_volume": "float64",  # volume na moeda de cotação (ex.: USDT)
        "trades": "Int64",
    }

    def __init__(self, symbols: list[str], timeframe: str = "1d", *, host: str = DEFAULT_HOST) -> None:
        if timeframe not in TIMEFRAME_MS:
            raise ValueError(f"timeframe não suportado: {timeframe}")
        if host not in ALLOWED_HOSTS:
            raise ValueError(f"host da Binance não suportado: {host} (aceitos: {', '.join(ALLOWED_HOSTS)})")
        self.host = host
        self.symbols = symbols      # formato "BTC/USDT"
        self.timeframe = timeframe

    def fetch(self, start: datetime | None, end: datetime) -> dict[str, list[list[Any]]]:
        """Velas fechadas em [start, end) por símbolo; a vela ainda aberta é descartada."""
        step = TIMEFRAME_MS[self.timeframe]
        start = start or end - DEFAULT_LOOKBACK
        start_ms = int(start.astimezone(timezone.utc).timestamp() * 1000)
        end_ms = int(end.astimezone(timezone.utc).timestamp() * 1000)
        raw: dict[str, list[list[Any]]] = {}
        for symbol in self.symbols:
            rows: list[list[Any]] = []
            since = start_ms
            while since < end_ms:
                page: list[list[Any]] = get_json(
                    self.host + KLINES_PATH,
                    {"symbol": symbol.replace("/", ""), "interval": self.timeframe,
                     "startTime": since, "endTime": end_ms - 1, "limit": PAGE_LIMIT},
                    min_interval=MIN_INTERVAL,
                )
                if not isinstance(page, list):
                    raise ExtractorError(f"{self.source}: resposta inesperada para {symbol}")
                if not page:
                    break
                rows.extend(k for k in page if int(k[0]) + step <= end_ms)
                since = int(page[-1][0]) + step
                if len(page) < PAGE_LIMIT:
                    break
            raw[symbol] = rows
        return raw

    def to_frame(self, raw: dict[str, list[list[Any]]]) -> pd.DataFrame:
        for symbol, rows in raw.items():
            if any(not isinstance(k, list) or len(k) <= max(_FIELDS) for k in rows):
                raise ExtractorError(f"{self.source}: candle incompleto para {symbol}")
        frames = [
            pd.DataFrame(rows).loc[:, list(_FIELDS)].rename(columns=_FIELDS).assign(symbol=symbol)
            for symbol, rows in raw.items()
            if rows
        ]
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        numeric = ["open", "high", "low", "close", "volume", "quote_volume"]
        df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
        return df
