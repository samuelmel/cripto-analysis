"""Configuração do projeto: universo de moedas, recomendação, qualidade de dados e backtest."""

from __future__ import annotations

UNIVERSE: dict[str, str] = {  # candidatas: par spot na Binance -> id no CoinGecko
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

MAX_EXTRA_COINS = 13
"""Quantas moedas além das RECOMMENDED entram na análise (as primeiras de UNIVERSE, na ordem)."""

MIN_HISTORY_DAYS = 365
"""Menos candles diários que isso e a moeda fica fora (a SMA 200 precisa de 200; sobra um ano de teste)."""

MIN_AVG_QUOTE_VOLUME_USD = 1_000_000.0
VOLUME_WINDOW_DAYS = 30
"""Volume médio diário (em USDT) dos últimos VOLUME_WINDOW_DAYS dias abaixo disso tira a moeda da análise."""

EXCLUDED_BASES: dict[str, str] = {
    "USDT": "stablecoin: o preço não se move, não há tendência a seguir",
    "USDC": "stablecoin",
    "FDUSD": "stablecoin",
    "TUSD": "stablecoin",
    "DAI": "stablecoin",
    "WBTC": "duplicata do BTC (BTC embrulhado em outra rede)",
    "WETH": "duplicata do ETH (ETH embrulhado)",
    "STETH": "derivativo do ETH (staking líquido): duplicata do ETH",
}
LEVERAGED_SUFFIXES: tuple[str, ...] = ("UP", "DOWN", "BULL", "BEAR")
"""Token alavancado = símbolo de outra moeda do UNIVERSE + um destes sufixos (ex.: BTCUP, ETHBEAR)."""

MAX_STALE_DAYS = 1
"""O último candle fechado pode estar até 1 dia mais velho que o esperado; além disso a moeda fica
INDISPONÍVEL (nunca gera sinal "atual" com dado velho)."""

REGIME_SYMBOL = "BTC/USDT"
"""Moeda cujo estado de tendência (acima/abaixo da SMA 200) vale como filtro de mercado para todas."""

TRAIN_PERIOD: tuple[str, str] = ("2018-01-01", "2022-12-31")
TEST_PERIOD: tuple[str, str] = ("2023-01-01", "2026-12-31")
"""Períodos do backtest de carteira: a regra foi escolhida no treino e conferida no teste."""

VALIDATION_PERIOD: tuple[str, str] = ("2021-01-01", TRAIN_PERIOD[1])
"""Parte final do treino usada para escolher parâmetros (laboratório de estratégias e previsão); o que vem antes
é só treino e o TEST_PERIOD nunca entra em escolha nenhuma."""

FORECAST_SEED = 20261015
"""Semente da previsão por bootstrap: fixa, para a mesma base dar sempre a mesma previsão."""

FEE_PER_SIDE = 0.001
"""Taxa de 0,1% sobre cada mudança de posição (entrar ou sair)."""
