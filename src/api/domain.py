"""Funções puras de apresentação: recebem linhas já publicadas e devolvem valores derivados."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .schemas import AssetSummary, DailySignal, MarketBrief, MarketRegime, Recommendation

REGIME_LABELS: dict[str, str] = {
    "FAVORAVEL": "Favorável",
    "NEUTRO": "Neutro",
    "DEFENSIVO": "Defensivo",
    "INDISPONIVEL": "Sem dados confiáveis",
}

COIN_NAMES: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BNB",
    "XRP": "XRP",
    "ADA": "Cardano",
    "DOGE": "Dogecoin",
    "AVAX": "Avalanche",
    "LINK": "Chainlink",
    "DOT": "Polkadot",
    "LTC": "Litecoin",
    "BCH": "Bitcoin Cash",
    "TRX": "TRON",
    "ATOM": "Cosmos",
    "ETC": "Ethereum Classic",
    "XLM": "Stellar",
    "FIL": "Filecoin",
    "NEAR": "NEAR Protocol",
    "UNI": "Uniswap",
    "AAVE": "Aave",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    "SUI": "Sui",
    "APT": "Aptos",
    "INJ": "Injective",
    "ALGO": "Algorand",
    "VET": "VeChain",
    "HBAR": "Hedera",
    "ICP": "Internet Computer",
    "PEPE": "Pepe",
    "SHIB": "Shiba Inu",
    "TON": "Toncoin",
}


def base_of(symbol: str) -> str:
    return symbol.split("/", 1)[0]


def name_of(symbol: str) -> str:
    base = base_of(symbol)
    return COIN_NAMES.get(base, base)


def regime_label(regime: str) -> str:
    return REGIME_LABELS.get(regime, regime)


def latest_regime(rows: Sequence[MarketRegime]) -> MarketRegime | None:
    valid = [row for row in rows if row.status == "OK"]
    if valid:
        return valid[-1]
    return rows[-1] if rows else None


def distance_pct(price: float | None, average: float | None) -> float | None:
    if price is None or average is None or average == 0:
        return None
    return (price / average - 1.0) * 100.0


def market_brief(
    signals: Sequence[DailySignal],
    recommendation: Recommendation,
    regime: MarketRegime | None,
) -> MarketBrief:
    btc = next((signal for signal in signals if signal.symbol == "BTC/USDT"), None)
    analyzed = [signal for signal in signals if signal.close > 0]
    breadth_up = sum(1 for signal in analyzed if signal.uptrend)
    breadth_down = sum(1 for signal in analyzed if not signal.uptrend)
    close = regime.close if regime is not None and regime.close is not None else (btc.close if btc is not None else None)
    sma_200 = None
    if btc is not None:
        sma_200 = btc.sma_200
    if close is not None and sma_200 is None and recommendation.regime_sma_200 is not None:
        sma_200 = recommendation.regime_sma_200
    as_of = recommendation.data_day
    fng = next((signal for signal in signals if signal.fng_value is not None), None)
    return MarketBrief(
        as_of=as_of,
        regime=recommendation.regime,
        regime_label=regime_label(recommendation.regime),
        fng_value=fng.fng_value if fng is not None else None,
        fng_classification=fng.fng_classification if fng is not None else None,
        btc_close=close,
        btc_sma_200=sma_200,
        btc_distance_pct=distance_pct(close, sma_200),
        breadth_up=breadth_up,
        breadth_down=breadth_down,
        n_analyzed=recommendation.n_analyzed,
        n_selected=recommendation.n_selected,
        total_allocated_brl=recommendation.total_brl,
    )


def asset_summary(signal: DailySignal) -> AssetSummary:
    return AssetSummary(
        symbol=signal.symbol,
        base=base_of(signal.symbol),
        name=name_of(signal.symbol),
        close=signal.close,
        ret_7d_pct=signal.ret_7d_pct,
        ret_30d_pct=signal.ret_30d_pct,
        ret_90d_pct=signal.ret_90d_pct,
        vol_90d_pct=signal.vol_90d_pct,
        score=signal.score,
        stage=signal.stage,
        opportunity=signal.opportunity,
        selected=signal.selected,
        allocation_brl=signal.allocation_brl,
        in_analysis=True,
    )


def ranked_assets(signals: Iterable[DailySignal]) -> list[AssetSummary]:
    order = {"BOA_RELATIVA": 0, "MODERADA": 1, "AGUARDAR": 2, "EVITAR": 3}
    rows = [asset_summary(signal) for signal in signals]
    return sorted(rows, key=lambda row: (order.get(row.opportunity or "EVITAR", 4), -(row.score or -1.0), row.symbol))
