"""Adaptador Bitstamp: candles diários de pares em USD pela API pública oficial (/api/v2/ohlc/{par}/).

A Bitstamp negocia BTC/USD desde agosto de 2011: é a série diária real mais longa de uma corretora ainda ativa, usada
para estender o histórico do BTC antes da Binance (2017). Só o host oficial é aceito. `fetch` faz a rede (paginado,
1.000 candles por chamada); `to_frame` e `standardize` são puros. O candle do dia ainda aberto é descartado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

import pandas as pd

from .base_extractor import BaseExtractor, ExtractorError
from .http import get_json

HOST = "https://www.bitstamp.net"
OHLC_PATH = "/api/v2/ohlc/{pair}/"
DAY_SECONDS = 86_400
PAGE_LIMIT = 1000
MIN_INTERVAL = 1.0  # s entre chamadas (limite público da Bitstamp: 400 por segundo; folga grande)
FIRST_DAY = datetime(2011, 8, 18, tzinfo=timezone.utc)  # primeiro candle de BTC/USD na Bitstamp


class BitstampAdapter(BaseExtractor):
    source: ClassVar[str] = "bitstamp"
    value_columns: ClassVar[dict[str, str]] = {
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "float64",        # volume no ativo base
        "quote_volume": "float64",  # aproximação: volume × fechamento (a API não traz o volume em USD)
    }

    def __init__(self, symbols: list[str]) -> None:
        for s in symbols:
            if not s.endswith("/USD") or s.count("/") != 1:
                raise ValueError(f"{s}: o adaptador da Bitstamp aceita pares em USD (ex.: BTC/USD)")
        self.symbols = symbols

    def fetch(self, start: datetime | None, end: datetime) -> dict[str, list[dict[str, Any]]]:
        """Candles diários fechados em [start, end) por par (start=None: desde 2011-08-18)."""
        begin = int((start or FIRST_DAY).astimezone(timezone.utc).timestamp())
        stop = int(end.astimezone(timezone.utc).timestamp())
        raw: dict[str, list[dict[str, Any]]] = {}
        for symbol in self.symbols:
            pair = symbol.replace("/", "").lower()
            rows: list[dict[str, Any]] = []
            since = begin
            while since < stop:
                payload = get_json(HOST + OHLC_PATH.format(pair=pair),
                                   {"step": DAY_SECONDS, "limit": PAGE_LIMIT, "start": since}, min_interval=MIN_INTERVAL)
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                    raise ExtractorError(f"{self.source}: resposta inesperada para {symbol}")
                page = payload["data"].get("ohlc", [])
                if not isinstance(page, list):
                    raise ExtractorError(f"{self.source}: resposta inesperada para {symbol}")
                fresh = [k for k in page if isinstance(k, dict) and since <= int(k.get("timestamp", -1)) < stop]
                rows.extend(k for k in fresh if int(k["timestamp"]) + DAY_SECONDS <= stop)
                if not fresh:
                    if rows:
                        break
                    since += PAGE_LIMIT * DAY_SECONDS  # o par ainda não existia: avança até o primeiro candle
                    continue
                since = max(int(k["timestamp"]) for k in fresh) + DAY_SECONDS
                if len(page) < PAGE_LIMIT:
                    break
            raw[symbol] = rows
        return raw

    def to_frame(self, raw: dict[str, list[dict[str, Any]]]) -> pd.DataFrame:
        frames = []
        for symbol, rows in raw.items():
            if not rows:
                continue
            df = pd.DataFrame(rows)
            missing = [c for c in ("timestamp", "open", "high", "low", "close", "volume") if c not in df.columns]
            if missing:
                raise ExtractorError(f"{self.source}: candle incompleto para {symbol}, faltam {missing}")
            num = {c: pd.to_numeric(df[c], errors="coerce") for c in ("open", "high", "low", "close", "volume")}
            frames.append(pd.DataFrame({
                "timestamp": pd.to_datetime(pd.to_numeric(df["timestamp"], errors="coerce"), unit="s", utc=True),
                "symbol": symbol, **num, "quote_volume": num["volume"] * num["close"],
            }))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).dropna(subset=["timestamp", "close"])
