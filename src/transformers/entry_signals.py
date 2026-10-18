"""Sinais de entrada candidatos: condições, eventos e retornos futuros. Protocolo: docs/entry_signals.md (fixado antes).

Puro (CLAUDE.md §1): recebe candles e regras, devolve quadros largos (índice = dia UTC, colunas = moedas). Toda condição
usa só dados até o fechamento de `t` (cortar os dados depois de `t` não muda a linha de `t`, testado); o futuro entra
apenas nos retornos medidos depois da entrada.

Candidatos (lista fechada, 11 combinações):
    A_N   retorno de N dias entre os `top_k` maiores do universo do dia                 N em {30, 60, 90}
    B_x   fechamento > SMA 100 e fechamento <= (1 − x) × máxima dos últimos 20 fechamentos  x em {10, 15, 20}%
    C     fechamento > maior fechamento dos 55 dias anteriores e volume em USD > média dos 20 dias anteriores
    D_N   retorno de N dias menos o do BTC entre os `top_k` maiores do universo e > 0   N em {30, 60, 90}
    E     score de seleção (`selection.score_components`) entre os `top_k` maiores do universo

Evento = entrada na condição: verdadeira em `t` e falsa no dia anterior (incalculável ou fora do universo conta como falso).
Execução: entrada na abertura de `t+1`, saída na abertura de `t+1+h` (sensibilidade: fechamentos), custos de `config.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config
from .selection import SelectionRules, compute_features, cost_per_side, score_components
from .strategies import Market
from .universe_pit import PitRules, membership

KIND_CROSS = "SELECAO"
"""Seleção entre moedas (A, D, E, F): referência = média do universo no mesmo dia."""
KIND_TIMING = "TEMPO"
"""Sinal de tempo por moeda (B, C): referência = dias elegíveis da mesma moeda."""

EXECUTION_OPEN = "ABERTURA"
EXECUTION_CLOSE = "FECHAMENTO"


@dataclass(frozen=True)
class EntryRules:
    top_k: int = 5
    momentum_windows: tuple[int, ...] = (30, 60, 90)
    pullback_sma: int = 100
    pullback_high_days: int = 20
    pullback_drops: tuple[float, ...] = (0.10, 0.15, 0.20)
    breakout_days: int = 55
    breakout_volume_days: int = 20
    horizons: tuple[int, ...] = config.VALIDATION_HORIZONS
    regime_symbol: str = config.REGIME_SYMBOL
    delisted_after_days: int = config.LONG_STALE_DAYS
    pit: PitRules = field(default_factory=PitRules)


@dataclass(frozen=True)
class Combo:
    """Uma combinação da grade: identificador estável (`A_30`, `B_15`, `C`, ...), candidato e tipo de referência."""

    combo_id: str
    candidate: str
    kind: str


def combos(rules: EntryRules = EntryRules()) -> tuple[Combo, ...]:
    """As 11 combinações de A a E, na ordem do protocolo."""
    out = [Combo(f"A_{n}", "A", KIND_CROSS) for n in rules.momentum_windows]
    out += [Combo(f"B_{round(x * 100)}", "B", KIND_TIMING) for x in rules.pullback_drops]
    out += [Combo("C", "C", KIND_TIMING)]
    out += [Combo(f"D_{n}", "D", KIND_CROSS) for n in rules.momentum_windows]
    out += [Combo("E", "E", KIND_CROSS)]
    return tuple(out)


@dataclass(frozen=True)
class Panel:
    """Quadros largos alinhados ao calendário diário."""

    open: pd.DataFrame
    close: pd.DataFrame
    quote_volume: pd.DataFrame
    member: pd.DataFrame       # universo point-in-time do dia
    cost: pd.DataFrame         # custo por lado (taxa + meia-largura do spread + slippage)
    delisted: tuple[str, ...]  # pararam de negociar (último candle há mais de `delisted_after_days` do fim dos dados)


def build_panel(candles: pd.DataFrame, rules: EntryRules = EntryRules()) -> Panel:
    """Quadros largos de abertura, fechamento, volume, universo e custo a partir dos candles (formato longo)."""
    if candles.empty:
        raise ValueError("candles vazios")

    def wide(col: str) -> pd.DataFrame:
        return candles.pivot(index="timestamp", columns="symbol", values=col).sort_index()

    close = wide("close")
    days = pd.date_range(close.index.min(), close.index.max(), freq="D", tz="UTC")
    close = close.reindex(days)
    open_ = wide("open").reindex(index=days, columns=close.columns)
    vol = wide("quote_volume").reindex(index=days, columns=close.columns)
    member = membership(candles, rules.pit).reindex(index=days, columns=close.columns).fillna(False).astype(bool)
    avg_volume = vol.rolling(rules.pit.volume_window_days, min_periods=1).mean()
    cost = cost_per_side(avg_volume, SelectionRules()).reindex_like(close)
    last = close.apply(lambda s: s.last_valid_index())
    end = days[-1]
    delisted = tuple(
        str(s) for s in close.columns if pd.notna(last[s]) and (end - last[s]).days > rules.delisted_after_days
    )
    return Panel(open_, close, vol, member, cost, delisted)


def _per_coin(frame: pd.DataFrame, fn: str, window: int, shift: int = 0) -> pd.DataFrame:
    """Janela móvel sobre os candles de cada moeda (dias sem candle não contam), alinhada ao calendário."""
    out = {}
    for symbol in frame.columns:
        col = frame[symbol].dropna()
        if shift:
            col = col.shift(shift)
        roll = col.rolling(window, min_periods=window)
        out[symbol] = (roll.mean() if fn == "mean" else roll.max()).reindex(frame.index)
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def trailing_return(close: pd.DataFrame, n: int) -> pd.DataFrame:
    """Retorno de `n` dias de calendário até `t` (NaN sem candle em `t` ou em `t − n`)."""
    return (close / close.shift(n) - 1.0).replace([np.inf, -np.inf], np.nan)


def top_k(values: pd.DataFrame, mask: pd.DataFrame, k: int) -> pd.DataFrame:
    """True para as `k` maiores de cada dia entre as linhas de `mask` com valor (empate: ordem das colunas)."""
    v = values.where(mask)
    rank = v.rank(axis=1, ascending=False, method="first")
    return rank.le(k) & v.notna()


@dataclass(frozen=True)
class Condition:
    """Estado diário de uma combinação: condição verdadeira e dias em que ela é calculável (base da referência)."""

    active: pd.DataFrame
    calculable: pd.DataFrame


def entries(active: pd.DataFrame) -> pd.DataFrame:
    """Evento = entrada na condição: verdadeira em `t` e falsa no dia anterior."""
    on = active.fillna(False).astype(bool)
    return on & ~on.shift(1, fill_value=False)


def selection_scores(candles: pd.DataFrame, member: pd.DataFrame) -> pd.DataFrame:
    """Score de seleção (0 a 100) de cada moeda em cada dia, com o percentil calculado só entre as moedas do universo
    do dia. Usa `selection.compute_features` (janelas para trás) e `score_components` (posto do mesmo dia)."""
    market = Market(
        close=candles.pivot(index="timestamp", columns="symbol", values="close").sort_index(),
        high=candles.pivot(index="timestamp", columns="symbol", values="high").sort_index(),
        low=candles.pivot(index="timestamp", columns="symbol", values="low").sort_index(),
        volume=candles.pivot(index="timestamp", columns="symbol", values="quote_volume").sort_index(),
    )
    rules = SelectionRules()
    features = compute_features(market, rules)
    out = pd.DataFrame(np.nan, index=member.index, columns=member.columns)
    for key, frame in features.groupby(level="timestamp", sort=True):
        day = pd.Timestamp(str(key))
        if day not in member.index:
            continue
        today = frame.droplevel("timestamp")
        row = member.loc[day]
        inside = today[today.index.isin(row.index[row.to_numpy()])]
        if inside.empty:
            continue
        out.loc[day, inside.index] = score_components(inside, rules)["score"].to_numpy()
    return out


def conditions(
    panel: Panel, rules: EntryRules = EntryRules(), scores: pd.DataFrame | None = None
) -> dict[str, Condition]:
    """Condição de cada combinação (`combos`). Sem `scores`, a combinação E não é calculada."""
    close, member = panel.close, panel.member
    out: dict[str, Condition] = {}
    for n in rules.momentum_windows:
        ret = trailing_return(close, n)
        ok = member & ret.notna()
        out[f"A_{n}"] = Condition(top_k(ret, ok, rules.top_k), ok)
        if rules.regime_symbol in close.columns:
            rel = ret.sub(ret[rules.regime_symbol], axis=0)
        else:
            rel = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        ok_rel = member & rel.notna()
        out[f"D_{n}"] = Condition(top_k(rel, ok_rel, rules.top_k) & rel.gt(0), ok_rel)

    sma = _per_coin(close, "mean", rules.pullback_sma)
    high = _per_coin(close, "max", rules.pullback_high_days)
    ok_b = member & close.notna() & sma.notna() & high.notna()
    for x in rules.pullback_drops:
        active = close.gt(sma) & close.le((1.0 - x) * high) & ok_b
        out[f"B_{round(x * 100)}"] = Condition(active, ok_b)

    prior_high = _per_coin(close, "max", rules.breakout_days, shift=1)
    prior_volume = _per_coin(panel.quote_volume, "mean", rules.breakout_volume_days, shift=1)
    ok_c = member & close.notna() & panel.quote_volume.notna() & prior_high.notna() & prior_volume.notna()
    out["C"] = Condition(close.gt(prior_high) & panel.quote_volume.gt(prior_volume) & ok_c, ok_c)

    if scores is not None:
        s = scores.reindex(index=close.index, columns=close.columns)
        ok_e = member & s.notna()
        out["E"] = Condition(top_k(s, ok_e, rules.top_k), ok_e)
    return out


def ranking_condition(values: pd.DataFrame, member: pd.DataFrame, k: int) -> Condition:
    """Condição "entre as `k` maiores do universo do dia" para um valor qualquer (usado pelo modelo F)."""
    ok = member & values.notna()
    return Condition(top_k(values, ok, k), ok)


def forward_returns(panel: Panel, h: int, execution: str = EXECUTION_OPEN) -> pd.DataFrame:
    """Retorno líquido de entrar em `t+1` e sair em `t+1+h` (aberturas, ou fechamentos na sensibilidade), com o custo
    por lado do dia da entrada nos dois lados. Moeda deslistada sai ao último preço; janela incompleta de moeda ativa
    fica NaN (descartada)."""
    if execution == EXECUTION_OPEN:
        price = panel.open.copy()
        if panel.delisted:
            last_close = panel.close[list(panel.delisted)].ffill()
            price[list(panel.delisted)] = panel.open[list(panel.delisted)].fillna(last_close)
    elif execution == EXECUTION_CLOSE:
        price = panel.close.copy()
        if panel.delisted:
            price[list(panel.delisted)] = panel.close[list(panel.delisted)].ffill()
    else:
        raise ValueError(f"execução desconhecida: {execution!r}")
    entry = price.shift(-1)
    exit_ = price.shift(-(1 + h))
    cost = panel.cost.shift(-1)
    out: pd.DataFrame = ((1.0 - cost) ** 2 * exit_ / entry - 1.0).replace([np.inf, -np.inf], np.nan)
    return out


def universe_reference(forward: pd.DataFrame, member: pd.DataFrame) -> pd.Series:
    """Média, com peso igual, do retorno futuro das moedas do universo de cada dia com janela completa."""
    values: pd.Series = forward.where(member).mean(axis=1, skipna=True)
    return values


def event_counts(events: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Número de eventos (todas as moedas) por combinação: só contagem, nenhum retorno."""
    rows = [{"combo": k, "n_events": int(v.to_numpy().sum()), "n_coins": int(v.any(axis=0).sum())} for k, v in events.items()]
    return pd.DataFrame(rows).astype({"combo": "string"})
