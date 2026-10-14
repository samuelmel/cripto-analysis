"""Adaptador Alternative.me: Crypto Fear & Greed Index diário (série global de mercado)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import pandas as pd

from .base_extractor import MARKET_SYMBOL, BaseExtractor

API_URL = "https://api.alternative.me/fng/"


class FearGreedAdapter(BaseExtractor):
    source: ClassVar[str] = "alternative_me"
    value_columns: ClassVar[dict[str, str]] = {
        "fng_value": "Int64",               # 0 (medo extremo) a 100 (ganância extrema)
        "fng_classification": "string",     # ex.: "Extreme Fear"
    }

    def fetch(self, start: datetime | None, end: datetime) -> Any:
        # TODO: GET API_URL?limit=0&format=json (histórico completo em uma chamada); filtrar [start, end).
        raise NotImplementedError

    def to_frame(self, raw: Any) -> pd.DataFrame:
        # TODO: data[].timestamp (segundos, string) -> timestamp; symbol = MARKET_SYMBOL.
        raise NotImplementedError
