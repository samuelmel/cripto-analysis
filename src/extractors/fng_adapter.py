"""Adaptador Alternative.me: Crypto Fear & Greed Index diário (série global de mercado)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import pandas as pd

from .base_extractor import MARKET_SYMBOL, BaseExtractor, ExtractorError
from .http import get_json

API_URL = "https://api.alternative.me/fng/"


class FearGreedAdapter(BaseExtractor):
    source: ClassVar[str] = "alternative_me"
    value_columns: ClassVar[dict[str, str]] = {
        "fng_value": "Int64",               # 0 (medo extremo) a 100 (ganância extrema)
        "fng_classification": "string",     # ex.: "Extreme Fear"
    }

    def fetch(self, start: datetime | None, end: datetime) -> list[dict[str, Any]]:
        """Leituras diárias mais recentes; `start=None` traz o histórico completo (limit=0)."""
        limit = 0 if start is None else max((end - start).days + 2, 1)
        payload = get_json(API_URL, {"limit": limit, "format": "json"})
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ExtractorError(f"{self.source}: resposta inesperada")
        data: list[dict[str, Any]] = payload["data"]
        return data

    def to_frame(self, raw: list[dict[str, Any]]) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        return pd.DataFrame(
            {
                "timestamp": pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="s", utc=True),
                "symbol": MARKET_SYMBOL,
                "fng_value": pd.to_numeric(df["value"], errors="coerce"),
                "fng_classification": df["value_classification"],
            }
        )
