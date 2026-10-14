"""Extratores (camada E do ETL): um adaptador por fonte, todos com o mesmo formato de saída."""

from .base_extractor import KEY_COLUMNS, MARKET_SYMBOL, BaseExtractor, ExtractorError
from .binance_adapter import BinanceAdapter
from .coingecko_adapter import CoinGeckoMarketAdapter, CoinGeckoTrendingAdapter
from .fng_adapter import FearGreedAdapter

__all__ = [
    "KEY_COLUMNS",
    "MARKET_SYMBOL",
    "BaseExtractor",
    "BinanceAdapter",
    "CoinGeckoMarketAdapter",
    "CoinGeckoTrendingAdapter",
    "ExtractorError",
    "FearGreedAdapter",
]
