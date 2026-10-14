"""Adaptador Binance: OHLCV e volume de pares spot.

Fontes (referência: extract_historical.py e extract_binance_vision.py na raiz):
    - data.binance.vision: ZIP mensal de klines, para backfill longo.
    - REST pública (/api/v3/klines, via CCXT): mês corrente e atualização diária.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import pandas as pd

from .base_extractor import BaseExtractor


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

    def __init__(self, symbols: list[str], timeframe: str = "1d") -> None:
        self.symbols = symbols      # formato "BTC/USDT"
        self.timeframe = timeframe

    def fetch(self, start: datetime | None, end: datetime) -> Any:
        # TODO: meses fechados via Binance Vision; mês corrente via REST; descartar vela aberta.
        raise NotImplementedError

    def to_frame(self, raw: Any) -> pd.DataFrame:
        # TODO: open_time -> timestamp (Vision usa µs desde 2025-01-01), symbol "BTCUSDT" -> "BTC/USDT".
        raise NotImplementedError
