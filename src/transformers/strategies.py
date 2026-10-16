"""Sinais de estratégia em formato largo (índice = dia, colunas = moedas), compartilhados pelo laboratório
(`research/lab.py`) e pela camada de seleção (`selection.py`).

Puro (CLAUDE.md §1). Lookahead: canais de rompimento e médias de volume usam só dias anteriores (`shift(1)`);
médias que incluem o fechamento de t são conhecidas no próprio fechamento de t.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RSI_PERIOD = 14
VOLUME_WINDOW = 20


@dataclass(frozen=True)
class Market:
    """Preços e volume em formato largo: índice = dia, colunas = moedas."""

    close: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame  # em USDT (quote_volume)


def market_from_candles(candles: pd.DataFrame) -> Market:
    """Candles padronizados (symbol, timestamp, high, low, close, quote_volume) -> Market."""

    def pivot(column: str) -> pd.DataFrame:
        return candles.pivot(index="timestamp", columns="symbol", values=column).sort_index()

    return Market(pivot("close"), pivot("high"), pivot("low"), pivot("quote_volume"))


def daily(market: Market) -> Market:
    """O mesmo Market com um dia por linha, sem pular dias (dia sem candle vira NaN): `shift(n)` = n dias."""
    if market.close.empty:
        return market
    days = pd.date_range(market.close.index.min(), market.close.index.max(), freq="D")
    return Market(*(f.reindex(days) for f in (market.close, market.high, market.low, market.volume)))


def latch(entry: pd.DataFrame, exit_: pd.DataFrame) -> pd.DataFrame:
    """Posição 0/1 que liga na entrada e desliga na saída (a saída vence se as duas ocorrerem no mesmo dia)."""
    state = pd.DataFrame(np.nan, index=entry.index, columns=entry.columns)
    state = state.mask(entry, 1.0).mask(exit_, 0.0)
    return state.ffill().fillna(0.0)


def donchian_breakout(m: Market, n: int) -> pd.DataFrame:
    """Compra ao fechar acima da máxima dos `n` dias anteriores; sai ao fechar abaixo da mínima dos `n // 2` anteriores."""
    upper = m.high.rolling(n).max().shift(1)
    lower = m.low.rolling(n // 2).min().shift(1)
    return latch(m.close.gt(upper), m.close.lt(lower))


def rsi(close: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
    """RSI de Wilder (EMA com alpha = 1/period), por moeda."""
    delta = close.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta).clip(lower=0.0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    out = 100.0 - 100.0 / (1.0 + gain / loss.replace(0.0, np.nan))
    return out.mask(loss.eq(0.0) & gain.notna(), 100.0)


def volume_breakout(m: Market, n: int, k: float) -> pd.DataFrame:
    """Rompimento da máxima de `n` dias com volume acima de `k` vezes a média de 20 dias; sai como a Donchian."""
    breakout = m.close.gt(m.high.rolling(n).max().shift(1))
    heavy = m.volume.gt(k * m.volume.rolling(VOLUME_WINDOW).mean().shift(1))
    lower = m.low.rolling(n // 2).min().shift(1)
    return latch(breakout & heavy, m.close.lt(lower))


def ema_cross(close: pd.DataFrame, fast: int, slow: int) -> pd.DataFrame:
    """1 enquanto a EMA rápida estiver acima da lenta (só depois de `slow` candles)."""
    f = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    s = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    return f.gt(s).astype(float)


def pullback_in_uptrend(close: pd.DataFrame, sma50: pd.DataFrame, sma200: pd.DataFrame, enter_z: float) -> pd.DataFrame:
    """1 no dia em que a moeda está em alta (preço e SMA 50 acima da SMA 200) e recuou abaixo de `enter_z`
    desvios da média de 20 dias: compra de recuo, nunca de queda em tendência de baixa."""
    mid = close.rolling(20).mean()
    z = (close - mid) / close.rolling(20).std(ddof=0).replace(0.0, np.nan)
    return (close.gt(sma200) & sma50.gt(sma200) & z.lt(enter_z)).astype(float)
