"""Configuração do projeto: universo de moedas, seleção, orçamento, qualidade de dados e backtest.

Único lugar de parâmetros (CLAUDE.md §1): os módulos de regra recebem estes valores por dataclasses de regras
(`UniverseRules`, `SelectionRules`, `AllocationRules`), com estes defaults; o entrypoint pode sobrescrever.
"""

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
    # Ampliação do universo (seleção dinâmica): pares spot USDT com liquidez relevante. As listadas há pouco
    # (ex.: SUI, TON) entram na base, mas só passam a ser analisadas quando tiverem MIN_HISTORY_DAYS candles.
    "NEAR/USDT": "near",
    "UNI/USDT": "uniswap",
    "ICP/USDT": "internet-computer",
    "FIL/USDT": "filecoin",
    "ETC/USDT": "ethereum-classic",
    "HBAR/USDT": "hedera-hashgraph",
    "AAVE/USDT": "aave",
    "ALGO/USDT": "algorand",
    "VET/USDT": "vechain",
    "INJ/USDT": "injective-protocol",
    "APT/USDT": "aptos",
    "ARB/USDT": "arbitrum",
    "OP/USDT": "optimism",
    "SUI/USDT": "sui",
    "TON/USDT": "the-open-network",
    "SHIB/USDT": "shiba-inu",
    "PEPE/USDT": "pepe",
}

RECOMMENDED: tuple[str, ...] = ("BTC/USDT", "ETH/USDT")
"""Moedas-núcleo da regra principal SMA 200 (referência preservada): recebem o estágio COMPRAR/PREPARAR, o
backtest de operações e a previsão, e nunca saem do universo. A recomendação de APORTE não se limita a elas:
vem da camada de seleção (`transformers/selection.py`), que avalia todas as moedas elegíveis do universo."""

MAX_UNIVERSE_SIZE = 32
"""Universo máximo analisado (núcleo incluído): as primeiras elegíveis de UNIVERSE, na ordem."""
MAX_EXTRA_COINS = MAX_UNIVERSE_SIZE - len(RECOMMENDED)
"""Quantas moedas além das RECOMMENDED entram na análise (derivado de MAX_UNIVERSE_SIZE)."""

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

LONG_STALE_DAYS = 30
"""Sem candle há mais que isso: além de desatualizada, a moeda é sinalizada como POSSÍVEL deslistagem, pausa ou
conversão do token. Não há fonte confiável de listagem na base, então a causa nunca é presumida (e a moeda nunca
é tratada como perda total)."""

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

# ---------------------------------------------------------------------------------------------
# Seleção de oportunidades (transformers/selection.py). Pesos e limiares definidos a priori, antes de olhar o
# período de teste; o estudo `research/selection_study.py` só mede a sensibilidade em treino e validação.
# ---------------------------------------------------------------------------------------------

MAX_CANDIDATES = 3
"""Quantas moedas, no máximo, aparecem como candidatas a compra (e no Telegram)."""

BUY_BLOCKLIST: dict[str, str] = {}
"""Exclusão manual só da COMPRA: a moeda continua analisada e no painel, mas nunca vira candidata.
Ex.: {"DOGE/USDT": "não quero memecoins"}. Para tirar da análise inteira, use EXCLUDED_BASES ou tire de UNIVERSE
(inclusão manual = acrescentar o par em UNIVERSE)."""

MIN_BUY_VOLUME_USD = 20_000_000.0
"""Volume médio diário (USDT, 30 dias) mínimo para ser candidata a compra. Mais exigente que o filtro do universo
(MIN_AVG_QUOTE_VOLUME_USD), que só decide o que é analisado."""

MIN_SCORE_HISTORY_DAYS = 250
"""Candles mínimos para pontuar uma moeda: 200 da SMA 200 + 50 dias para medir a persistência da tendência."""

MAX_GAP_DAYS_365 = 3
"""Mais dias faltando que isso nos últimos 365 (integridade do histórico) impede a recomendação."""

SCORE_WEIGHTS: dict[str, float] = {
    "momentum": 0.35,   # retorno de 30 e 90 dias ajustado pela volatilidade (um componente só, não três)
    "stability": 0.20,  # persistência: % dos últimos 50 dias acima da SMA 200
    "risk": 0.25,       # volatilidade de 90 dias e pior queda de 180 dias (menor = melhor)
    "liquidity": 0.20,  # volume médio de 30 dias
}
"""Pesos do score (somam 1). Cada componente é o percentil da moeda entre as analisadas no dia (0 a 100), então
nenhum indicador domina pela escala. Força relativa contra as outras moedas é o próprio percentil do momento;
contra o BTC é mostrada, mas não somada de novo (seria contar o mesmo retorno duas vezes)."""

SCORE_STRONG = 65.0
"""Score mínimo para 'boa oportunidade relativa' (com todos os filtros e sem alerta de risco)."""
SCORE_MODERATE = 50.0
"""Score mínimo para 'oportunidade moderada'. Abaixo disso: aguardar."""

MIN_CONDITIONS = 3
"""Condições independentes favoráveis (das estratégias habilitadas) exigidas para recomendar uma entrada."""

ENABLED_SETUPS: tuple[str, ...] = ("sma200", "ema_cross", "donchian", "momentum")
"""Estratégias que contam como condição favorável. Disponíveis também: "volume_breakout" e "pullback"
(queda dentro da alta), desligadas porque perderam para a tendência no laboratório (`research/strategy_lab.py`)."""

SETUP_PARAMS: dict[str, dict[str, float]] = {
    "ema_cross": {"fast": 20, "slow": 50},
    "donchian": {"n": 55},
    "momentum": {"days": 90},
    "volume_breakout": {"n": 55, "k": 1.5},
    "pullback": {"enter_z": -1.0},
}

MAX_VOLATILITY = 1.50
"""Volatilidade anualizada de 90 dias acima disso (150% ao ano) = risco excessivo: evitar entrada."""
HIGH_VOLATILITY = 0.90
"""Acima disso (90% ao ano) a moeda leva o alerta de volatilidade elevada e não passa de 'moderada'."""
MAX_DRAWDOWN_180D = 0.60
"""Pior queda de 180 dias maior que 60% = risco excessivo: evitar entrada."""
MAX_STRETCH = 1.5
"""Distância acima da SMA 50 maior que 1,5 vez a oscilação típica de 50 dias = movimento estendido: aguardar."""
MAX_RSI_ENTRY = 80.0
"""RSI de 14 dias acima disso = sobrecomprado: aguardar (nunca é, sozinho, motivo para comprar)."""

REGIME_FILTER = "bloquear"
"""Filtro de regime (BTC abaixo da SMA 200): "bloquear" = nenhuma compra nova em nenhuma moeda (padrão, igual à
regra principal); "reduzir" = metade do orçamento-alvo; "desligado" = só sinaliza. Validação: selection_study."""

# ---------------------------------------------------------------------------------------------
# Orçamento e alocação (transformers/allocation.py)
# ---------------------------------------------------------------------------------------------

BUDGET_BRL = 100.0
"""Orçamento TOTAL para novas posições na análise (não é por moeda nem aporte obrigatório). Sem integração com
saldo real: cada execução é uma simulação para este valor. Já aportou? Rode com --budget <saldo restante>."""

MAX_POSITIONS = 3
"""Posições novas simultâneas na mesma análise."""
MAX_ALLOCATION_PCT = 0.40
"""Limite por moeda: no máximo 40% do orçamento."""
TARGET_VOL_PER_POSITION = 0.30
"""Dimensionamento por volatilidade: fração-alvo do orçamento = 30% / volatilidade anual da moeda (BTC com 50% ao
ano -> 60%, limitado a MAX_ALLOCATION_PCT; altcoin com 100% ao ano -> 30%). Moeda mais arriscada recebe menos."""
CONVICTION: dict[str, float] = {"BOA_RELATIVA": 1.0, "MODERADA": 0.5}
"""Multiplicador da fração-alvo por classificação. Aguardar e evitar = 0."""
REGIME_REDUCE_FACTOR = 0.5
"""Fator do orçamento-alvo com REGIME_FILTER = "reduzir" e BTC abaixo da SMA 200."""

ROUND_TO_BRL = 5.0
"""Aportes arredondados PARA BAIXO em múltiplos de R$ 5 (a soma nunca passa do orçamento)."""
MIN_ORDER_BRL = 10.0
"""Ordem mínima da corretora em reais (confira a sua; pares em USDT da Binance pedem cerca de 5 USDT). Aporte
abaixo disso é zerado e o motivo aparece na recomendação."""
FIXED_COST_BRL = 0.0
"""Custo fixo por ordem (tarifa, transferência). Com valor > 0, aporte em que ele passa de MAX_COST_PCT é zerado."""
MAX_COST_PCT = 0.02
"""Custo total estimado (fixo + taxa + spread + slippage) acima de 2% do aporte = economicamente inviável."""

SPREAD_TIERS: tuple[tuple[float, float], ...] = ((500_000_000.0, 0.0002), (50_000_000.0, 0.0005), (0.0, 0.0015))
"""Spread estimado por faixa de volume médio diário (USDT): (volume mínimo, meia-largura do spread). É uma
hipótese conservadora (não há livro de ofertas nas fontes integradas), não uma medida."""
SLIPPAGE = 0.0005
"""Slippage estimado por lado (0,05%) para ordens pequenas a mercado."""

# ---------------------------------------------------------------------------------------------
# Classificação de regimes de mercado (transformers/regimes.py). Valores fixados a priori, por critério econômico,
# sem olhar o desempenho de nenhuma estratégia. Mudou aqui, muda `params_hash` na saída (rastreabilidade).
# ---------------------------------------------------------------------------------------------

REGIME_MA_WINDOW = 200
"""Média móvel de tendência de longo prazo (dias), a mesma referência da regra principal."""
REGIME_SLOPE_DAYS = 30
"""Inclinação = variação da média móvel em 30 dias (a média de 200 dias muda devagar; 30 dias separa alta de queda)."""
REGIME_TREND_BAND = 0.05
"""Zona morta do preço em torno da média: dentro de ±5% o preço não está nem acima nem abaixo com clareza."""
REGIME_SLOPE_FLAT = 0.02
"""Zona morta da inclinação: a média variar menos de ±2% em 30 dias vale como 'plana'."""
REGIME_CONFIRM_DAYS = 5
"""Um estado de tendência só é adotado depois de 5 dias seguidos iguais (reduz trocas por ruído). Custo: atraso."""
REGIME_VOL_WINDOW = 30
"""Volatilidade realizada: desvio dos retornos log de 30 dias, anualizado (365)."""
REGIME_VOL_ENTER = 0.80
"""Entra em volatilidade ALTA quando a volatilidade de hoje supera 80% dos valores do PASSADO do próprio ativo."""
REGIME_VOL_EXIT = 0.70
"""Sai de volatilidade ALTA quando cai abaixo do percentil 70 do passado (histerese: evita oscilar no limiar)."""
REGIME_VOL_MIN_HISTORY = 365
"""Observações passadas de volatilidade exigidas antes de classificar a volatilidade (aquecimento do percentil)."""
REGIME_MIN_COVERAGE = 0.90
"""Fração mínima de dias com candle dentro de cada janela. Abaixo disso o regime fica DADOS_INCOMPLETOS; nada é
preenchido com zero nem com preço repetido."""

SELECTION_REBALANCE_DAYS = 7
"""Backtest da seleção: a carteira simulada segue a recomendação a cada 7 dias (rodar todo dia trocaria de
moeda por ruído e pagaria mais custo)."""
REBALANCE_BAND = 0.05
"""Backtest: moeda que continua na carteira só é reajustada se o peso-alvo mudar mais de 5 pontos percentuais
(entradas e saídas sempre são executadas). Evita pagar custo por ajustes pequenos."""

# ---------------------------------------------------------------------------------------------
# Validação estatística do COMPRAR (transformers/signal_validation.py, docs/signal_validation.md). Regras fixadas
# ANTES de olhar qualquer resultado de retorno.
# ---------------------------------------------------------------------------------------------

PIT_EXCLUDED_BASES: tuple[str, ...] = (
    # stablecoins e paridades de moeda fiduciária (não há tendência de cripto a seguir)
    "USDC", "BUSD", "TUSD", "USDP", "USDS", "FDUSD", "DAI", "UST", "USTC", "PYUSD", "USD1", "XUSD", "BFUSD", "AEUR",
    "EURI", "EUR", "GBP", "AUD", "TRY", "BRL", "RUB", "UAH", "ZAR", "NGN", "PLN", "RON", "ARS", "JPY", "CZK", "MXN",
    "COP", "IDR", "BIDR", "IDRT", "VAI", "SUSD", "USDSB", "USDT",
    # duplicatas e derivativos de BTC/ETH, ouro tokenizado
    "WBTC", "WETH", "STETH", "WBETH", "BETH", "PAXG", "XAUT",
)
"""Bases fora do universo point-in-time (a lista de `EXCLUDED_BASES` mais fiduciárias e variantes de stablecoin)."""

HOLDOUT_START = "2025-01-01"
"""Início do teste final. Nada antes dele pode ser escolhido com dados dele; nada nele escolhe nada."""
DEVELOPMENT_END = "2024-12-31"
"""Último dia do período de desenvolvimento (inclui o 2023+ antigo, já consumido)."""

VALIDATION_HORIZONS: tuple[int, ...] = (7, 30)
"""Horizontes (dias) do retorno depois da entrada simulada."""
VALIDATION_ALPHA = 0.05
"""Nível do teste, com correção de Holm sobre a família de combinações (moeda, horizonte) testadas."""
VALIDATION_SEED = 20261016
"""Semente-base: a semente de cada (moeda, horizonte) deriva dela de forma estável."""
VALIDATION_NULL_DRAWS = 20_000
"""Sorteios da referência aleatória (dias de entrada aleatórios da mesma moeda)."""
VALIDATION_BOOTSTRAP_RESAMPLES = 2_000
"""Reamostragens do bootstrap em blocos do intervalo de confiança."""
HOLDOUT_MIN_SIGNALS = 5
"""Sinais independentes mínimos no hold-out para ele poder revogar (ou confirmar) uma moeda validada."""
