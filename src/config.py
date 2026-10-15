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

RECOMMENDED: tuple[str, ...] = ("BTC/USDT", "ETH/USDT")
"""Moedas que recebem recomendação de compra. As demais do UNIVERSE são só monitoradas."""

REGIME_SYMBOL = "BTC/USDT"
"""Moeda cujo estado de tendência (acima/abaixo da SMA 200) vale como filtro de mercado para todas."""

TRAIN_PERIOD: tuple[str, str] = ("2018-01-01", "2022-12-31")
TEST_PERIOD: tuple[str, str] = ("2023-01-01", "2026-12-31")
"""Períodos do backtest de carteira: a regra foi escolhida no treino e conferida no teste."""

FEE_PER_SIDE = 0.001
"""Taxa de 0,1% sobre cada mudança de posição (entrar ou sair)."""
