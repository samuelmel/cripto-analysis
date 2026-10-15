"""Universo de ativos monitorados: par spot na Binance -> id no CoinGecko."""

from __future__ import annotations

UNIVERSE: dict[str, str] = {
    "BTC/USDT": "bitcoin",
    "ETH/USDT": "ethereum",
    "BNB/USDT": "binancecoin",
    "SOL/USDT": "solana",
    "XRP/USDT": "ripple",
    "ADA/USDT": "cardano",
    "DOGE/USDT": "dogecoin",
    "TRX/USDT": "tron",
    "AVAX/USDT": "avalanche-2",
    "LINK/USDT": "chainlink",
    "DOT/USDT": "polkadot",
    "LTC/USDT": "litecoin",
    "BCH/USDT": "bitcoin-cash",
    "ATOM/USDT": "cosmos",
    "XLM/USDT": "stellar",
}
