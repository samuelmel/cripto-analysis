"""Adaptadores CoinGecko: market cap (série histórica) e tendências (snapshot).

As duas consultas têm granularidades diferentes, por isso são dois adaptadores com schemas
próprios. Ambos exigem a chave Demo gratuita em `COINGECKO_API_KEY` (header x-cg-demo-api-key).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, ClassVar

import pandas as pd

from .base_extractor import BaseExtractor

API_URL = "https://api.coingecko.com/api/v3"


class _CoinGeckoBase(BaseExtractor):
    source: ClassVar[str] = "coingecko"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("COINGECKO_API_KEY")


class CoinGeckoMarketAdapter(_CoinGeckoBase):
    """Preço, market cap e volume diário por moeda. Plano Demo: até 365 dias de histórico."""

    value_columns: ClassVar[dict[str, str]] = {
        "price_usd": "float64",
        "market_cap_usd": "float64",
        "total_volume_usd": "float64",
    }

    def __init__(self, coin_ids: list[str], api_key: str | None = None) -> None:
        super().__init__(api_key)
        self.coin_ids = coin_ids    # ids do CoinGecko (ex.: "bitcoin")

    def fetch(self, start: datetime | None, end: datetime) -> Any:
        # TODO: GET {API_URL}/coins/{id}/market_chart/range?vs_currency=usd&from=&to= por coin_id.
        raise NotImplementedError

    def to_frame(self, raw: Any) -> pd.DataFrame:
        # TODO: unir prices/market_caps/total_volumes por timestamp (ms); symbol = ticker em maiúsculas.
        raise NotImplementedError


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
