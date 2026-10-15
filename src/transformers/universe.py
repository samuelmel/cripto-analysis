"""Seleção do universo analisado: aplica as regras de `src/config.py` às moedas candidatas.

Puro (CLAUDE.md §1): recebe o dicionário de candidatas e os candles da base local e devolve quem fica
e por que cada uma das outras saiu. Ordem das regras (a primeira que pega dá o motivo):

    excluída       base listada em EXCLUDED_BASES (stablecoins, duplicatas do BTC/ETH)
    alavancada     símbolo de outra candidata + sufixo de LEVERAGED_SUFFIXES
    duplicada      mesma base ou mesmo id do CoinGecko de uma candidata anterior
    sem candles    nenhum candle na base
    histórico      menos de MIN_HISTORY_DAYS candles diários
    volume         volume médio (quote_volume) dos últimos VOLUME_WINDOW_DAYS dias abaixo do mínimo
    limite         além de MAX_EXTRA_COINS moedas adicionais

As moedas RECOMMENDED nunca saem por histórico, volume ou limite: sem dado elas ficam INDISPONÍVEIS
(ver `data_quality`) em vez de sumirem. Recomendada excluída ou fora das candidatas é erro de configuração.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from .. import config


@dataclass(frozen=True)
class UniverseRules:
    recommended: tuple[str, ...] = config.RECOMMENDED
    max_extra: int = config.MAX_EXTRA_COINS
    min_history_days: int = config.MIN_HISTORY_DAYS
    min_avg_quote_volume: float = config.MIN_AVG_QUOTE_VOLUME_USD
    volume_window_days: int = config.VOLUME_WINDOW_DAYS
    excluded: Mapping[str, str] = field(default_factory=lambda: dict(config.EXCLUDED_BASES))
    leveraged_suffixes: tuple[str, ...] = config.LEVERAGED_SUFFIXES


@dataclass(frozen=True)
class UniverseSelection:
    kept: tuple[str, ...]
    dropped: Mapping[str, str]  # símbolo -> motivo


def _base(symbol: str) -> str:
    return symbol.split("/", 1)[0].upper()


def select_universe(
    candidates: Mapping[str, str], candles: pd.DataFrame, rules: UniverseRules = UniverseRules()
) -> UniverseSelection:
    """Quais `candidates` (símbolo -> id CoinGecko) entram na análise, dado o que há em `candles`."""
    unknown = [s for s in rules.recommended if s not in candidates]
    if unknown:
        raise ValueError(f"RECOMMENDED fora do UNIVERSE: {unknown}")
    bad = [s for s in rules.recommended if _base(s) in rules.excluded]
    if bad:
        raise ValueError(f"RECOMMENDED excluída em EXCLUDED_BASES: {bad}")

    bases = {_base(s) for s in candidates}
    days = candles.groupby("symbol")["timestamp"].nunique() if not candles.empty else pd.Series(dtype="int64")
    volume = _recent_volume(candles, rules.volume_window_days)

    kept: list[str] = []
    dropped: dict[str, str] = {}
    seen_bases: set[str] = set()
    seen_ids: set[str] = set()
    extra = 0
    for symbol, coin_id in candidates.items():
        base = _base(symbol)
        recommended = symbol in rules.recommended
        reason: str | None = None
        if base in rules.excluded:
            reason = f"excluída: {rules.excluded[base]}"
        elif any(base.endswith(sfx) and base[: -len(sfx)] in bases for sfx in rules.leveraged_suffixes):
            reason = "token alavancado"
        elif base in seen_bases or coin_id in seen_ids:
            reason = "duplicada"
        elif not recommended:
            n = int(days.get(symbol, 0))
            if n == 0:
                reason = "sem candles na base"
            elif n < rules.min_history_days:
                reason = f"histórico curto: {n} dias (mínimo {rules.min_history_days})"
            elif float(volume.get(symbol, 0.0)) < rules.min_avg_quote_volume:
                reason = (
                    f"volume médio de {float(volume.get(symbol, 0.0)):,.0f} USDT por dia "
                    f"(mínimo {rules.min_avg_quote_volume:,.0f})"
                )
            elif extra >= rules.max_extra:
                reason = f"acima do limite de {rules.max_extra} moedas adicionais"
        if reason is not None:
            dropped[symbol] = reason
            continue
        seen_bases.add(base)
        seen_ids.add(coin_id)
        extra += 0 if recommended else 1
        kept.append(symbol)
    return UniverseSelection(tuple(kept), dropped)


def _recent_volume(candles: pd.DataFrame, window_days: int) -> pd.Series:
    """Volume médio diário (quote_volume) de cada símbolo nos últimos `window_days` dias da sua própria base."""
    if candles.empty or "quote_volume" not in candles.columns:
        return pd.Series(dtype="float64")
    last = candles.groupby("symbol")["timestamp"].transform("max")
    recent = candles[candles["timestamp"].gt(last - pd.Timedelta(days=window_days))]
    return recent.groupby("symbol")["quote_volume"].mean()
