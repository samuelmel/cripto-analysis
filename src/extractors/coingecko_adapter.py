"""Adaptadores CoinGecko: market cap atual e tendências (ambos snapshots do momento).

Schemas diferentes, por isso dois adaptadores. A chave Demo gratuita, se existir em
`COINGECKO_API_KEY`, vai no header x-cg-demo-api-key.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, ClassVar

import pandas as pd

from .base_extractor import BaseExtractor, ExtractorError
from .http import get_json

logger = logging.getLogger(__name__)

API_URL = "https://api.coingecko.com/api/v3"
MIN_INTERVAL = 1.0  # s entre chamadas; plano Demo: 100 chamadas/min e 10 mil/mês (docs.coingecko.com, 2026-10)
_REQUIRED = ("last_updated", "symbol", "current_price", "market_cap", "total_volume")


class _CoinGeckoBase(BaseExtractor):
    source: ClassVar[str] = "coingecko"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("COINGECKO_API_KEY")


class CoinGeckoMarketAdapter(_CoinGeckoBase):
    """Preço, market cap e volume 24h atuais por moeda (/coins/markets, uma chamada para todas).

    É um snapshot: start/end são ignorados. A chave Demo é opcional aqui (sem ela, limite menor).
    """

    value_columns: ClassVar[dict[str, str]] = {
        "price_usd": "float64",
        "market_cap_usd": "float64",
        "total_volume_usd": "float64",
    }

    def __init__(self, coin_ids: list[str], api_key: str | None = None) -> None:
        super().__init__(api_key)
        self.coin_ids = coin_ids    # ids do CoinGecko (ex.: "bitcoin")

    def fetch(self, start: datetime | None, end: datetime) -> list[dict[str, Any]]:
        headers = {"x-cg-demo-api-key": self.api_key} if self.api_key else None
        payload = get_json(
            f"{API_URL}/coins/markets",
            {"vs_currency": "usd", "ids": ",".join(self.coin_ids), "per_page": 250},
            headers,
            min_interval=MIN_INTERVAL,
        )
        if not isinstance(payload, list) or not payload:
            raise ExtractorError(f"{self.source}: resposta inesperada ou vazia")
        data: list[dict[str, Any]] = payload
        absent = sorted(set(self.coin_ids) - {str(c.get("id")) for c in data})
        if absent:
            logger.warning("%s: moedas ausentes na resposta: %s", self.source, ", ".join(absent))
        return data

    def to_frame(self, raw: list[dict[str, Any]]) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        missing = [c for c in _REQUIRED if c not in df.columns]
        if missing:
            raise ExtractorError(f"{self.source}: resposta incompleta, faltam campos {missing}")
        return pd.DataFrame(
            {
                "timestamp": pd.to_datetime(df["last_updated"], utc=True, errors="coerce"),
                "symbol": df["symbol"].str.upper(),
                "price_usd": pd.to_numeric(df["current_price"], errors="coerce"),
                "market_cap_usd": pd.to_numeric(df["market_cap"], errors="coerce"),
                "total_volume_usd": pd.to_numeric(df["total_volume"], errors="coerce"),
            }
        )


class CoinGeckoTrendingAdapter(_CoinGeckoBase):
    """Top moedas em tendência no momento da execução (sem histórico na API)."""

    value_columns: ClassVar[dict[str, str]] = {
        "trending_rank": "Int64",       # 1 = mais buscada nas últimas 24h
        "market_cap_rank": "Int64",
        "coin_id": "string",
    }

    def fetch(self, start: datetime | None, end: datetime) -> Any:
        # TODO: GET {API_URL}/search/trending. start/end são ignorados: a API só expõe o snapshot atual.
        raise NotImplementedError

    def to_frame(self, raw: Any) -> pd.DataFrame:
        # TODO: timestamp = horário da extração truncado ao dia; uma linha por moeda em coins[].item.
        raise NotImplementedError
