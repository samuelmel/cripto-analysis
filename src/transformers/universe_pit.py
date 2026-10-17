"""Universo point-in-time: quem pertence ao universo em cada dia usando SOMENTE dados até aquele dia.

Puro (CLAUDE.md §1). O universo atual (`universe.select_universe`) olha o volume de hoje para decidir quem entra,
o que escolhe com informação do futuro e esquece as moedas que deixaram de negociar. Aqui, a cada dia `D`:

    elegível   candles até `D` suficientes (`min_history_days`), candle recente (até `max_stale_days` de atraso) e
               volume médio dos últimos `volume_window_days` dias (em USDT) acima do mínimo
    membro     elegível E entre as `max_size` de maior volume do dia

Todas as operações são causais (somas e médias móveis para trás, posto do mesmo dia): cortar os dados depois de `D`
não muda a linha de `D` (testado). Candidatas incluem pares deslistados quando a base os tem; a exclusão por nome
(stablecoins, fiduciárias, alavancadas) usa só o símbolo.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config


@dataclass(frozen=True)
class PitRules:
    min_history_days: int = config.MIN_HISTORY_DAYS
    min_avg_quote_volume: float = config.MIN_AVG_QUOTE_VOLUME_USD
    volume_window_days: int = config.VOLUME_WINDOW_DAYS
    max_stale_days: int = config.MAX_STALE_DAYS
    max_size: int = config.MAX_UNIVERSE_SIZE
    excluded: frozenset[str] = field(default_factory=lambda: frozenset(config.PIT_EXCLUDED_BASES))
    leveraged_suffixes: tuple[str, ...] = config.LEVERAGED_SUFFIXES


def _base(symbol: str) -> str:
    return symbol.split("/", 1)[0].upper()


def candidate_symbols(symbols: Iterable[str], rules: PitRules = PitRules()) -> tuple[str, ...]:
    """Símbolos que podem entrar no universo por NOME: fora stablecoins, fiduciárias e tokens alavancados."""
    names = sorted(set(symbols))
    bases = {_base(s) for s in names}
    keep: list[str] = []
    for symbol in names:
        base = _base(symbol)
        if base in rules.excluded:
            continue
        if any(base.endswith(sfx) and base[: -len(sfx)] in bases for sfx in rules.leveraged_suffixes):
            continue
        keep.append(symbol)
    return tuple(keep)


def membership(candles: pd.DataFrame, rules: PitRules = PitRules()) -> pd.DataFrame:
    """Pertencimento diário ao universo: índice = dia (UTC), colunas = símbolos, valor booleano.

    `candles` precisa de `timestamp`, `symbol`, `quote_volume`. A linha de `D` só depende de candles com data <= `D`.
    """
    if candles.empty:
        return pd.DataFrame(dtype=bool)
    vol = candles.pivot(index="timestamp", columns="symbol", values="quote_volume").sort_index()
    days = pd.date_range(vol.index.min(), vol.index.max(), freq="D", tz="UTC")
    vol = vol.reindex(days)
    has = vol.notna()
    history = has.cumsum()
    seen = pd.DataFrame(
        np.where(has.to_numpy(), np.arange(len(days))[:, None], np.nan), index=days, columns=vol.columns
    ).ffill()
    stale = (pd.Series(np.arange(len(days)), index=days).to_numpy()[:, None] - seen.to_numpy())
    fresh = pd.DataFrame(stale <= rules.max_stale_days, index=days, columns=vol.columns)
    avg = vol.rolling(rules.volume_window_days, min_periods=1).mean()
    eligible = fresh & history.ge(rules.min_history_days) & avg.ge(rules.min_avg_quote_volume)
    rank = avg.where(eligible).rank(axis=1, ascending=False, method="first")
    return eligible & rank.le(rules.max_size)


def universe_on(candles: pd.DataFrame, day: pd.Timestamp, rules: PitRules = PitRules()) -> tuple[str, ...]:
    """Universo do dia `day`, calculado só com candles até `day` (corta o futuro antes de qualquer cálculo)."""
    known = candles[candles["timestamp"].le(day)]
    members = membership(known, rules)
    if members.empty or day not in members.index:
        return ()
    row = members.loc[day]
    return tuple(sorted(str(s) for s in row.index[row.to_numpy()]))
