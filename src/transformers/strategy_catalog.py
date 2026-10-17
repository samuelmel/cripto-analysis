"""Catálogo das estratégias que o projeto já testou, como sinais 0/1 decididos no fechamento de D.

Puro (CLAUDE.md §1). Reúne, com uma só interface, as regras do painel, do estudo de comparação
(`research/strategy_comparison.py`) e do laboratório (`research/lab.py`), para a validação estatística avaliar TODAS
na mesma família (testar muitas e reportar só a melhor é o vício que a correção para comparações múltiplas corrige).

Cada estratégia fixa tem variações MODERADAS de parâmetro, declaradas aqui antes dos resultados (sensibilidade, não
otimização). As de grade trazem todos os candidatos; o walk-forward escolhe entre eles só com a validação de cada
dobra.

Sem olhar para frente: médias e retornos usam só o passado e o próprio fechamento de D; canais de rompimento e
médias de volume usam `shift(1)` (ver `strategies.py`). `tests/test_validation_protocol.py` confere que cortar os
dados depois de D não muda nenhum sinal até D.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from .panic_backtest import panic_trades
from .strategies import (
    Market,
    bollinger_reversion,
    daily,
    dip_in_uptrend,
    donchian_breakout,
    rsi_oversold,
    volume_breakout,
)
from .trade_simulator import ExitRules, positions_from_trades, trend_positions, wide


@dataclass(frozen=True)
class SignalSpec:
    """Um sinal fixo com suas variações moderadas, ou uma grade de candidatos (`grid`)."""

    name: str
    description: str
    signal: pd.DataFrame | None                         # None nas estratégias de grade
    params: Mapping[str, object] = field(default_factory=dict)
    variants: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    grid: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    requires_fng: bool = False


def trend_signal(
    history: pd.DataFrame,
    sma_days: int = 200,
    stop_loss: float | None = -0.20,
    btc_filter: bool = True,
    regime_symbol: str = "BTC/USDT",
) -> pd.DataFrame:
    """Tendência: moeda acima da própria SMA de `sma_days` (e, com `btc_filter`, BTC acima da sua), com o STOP de
    `trade_simulator.trend_positions`. Com 200 dias, filtro e STOP de −20% é a regra do painel."""
    px = wide(history, "close")
    above = px.gt(px.rolling(sma_days, min_periods=sma_days).mean())
    if btc_filter:
        btc = above[regime_symbol] if regime_symbol in above.columns else pd.Series(False, index=above.index)
        above = above & btc.to_numpy()[:, None]
    stacked = pd.Series(above.stack(), name="uptrend")
    long = stacked.rename_axis(["timestamp", "symbol"]).reset_index()
    h = history[["symbol", "timestamp", "close"]].merge(long, on=["symbol", "timestamp"], how="left")
    h["uptrend"] = h["uptrend"].fillna(False).astype(bool)
    return trend_positions(h, ExitRules(stop_loss=stop_loss)).reindex_like(px).fillna(0.0)


def _cross(px: pd.DataFrame, fast: int, slow: int) -> pd.DataFrame:
    f = px.rolling(fast, min_periods=fast).mean()
    s = px.rolling(slow, min_periods=slow).mean()
    return f.gt(s).astype(float)


def _momentum(px: pd.DataFrame, days: int) -> pd.DataFrame:
    return (px / px.shift(days) - 1.0).gt(0).astype(float)


def _dip(px: pd.DataFrame, history: pd.DataFrame, enter_z: float) -> pd.DataFrame:
    return dip_in_uptrend(px, wide(history, "sma_200"), wide(history, "zscore_90"), enter_z=enter_z)


def _label(params: Mapping[str, float]) -> str:
    return ", ".join(f"{k}={v:g}" for k, v in params.items())


GRID_PARAMS: dict[str, list[dict[str, float]]] = {  # os mesmos candidatos de research/lab.py (GRIDS)
    "DONCHIAN": [{"n": n} for n in (20, 55, 100)],
    "BOLLINGER": [{"n": n, "k": k} for n in (20, 50) for k in (1.5, 2.0, 2.5)],
    "RSI_SOBREVENDIDO": [{"buy_below": b, "sell_above": s} for b in (20, 25, 30, 35) for s in (50, 70)],
    "ROMPIMENTO_VOLUME": [{"n": n, "k": k} for n in (20, 55) for k in (1.0, 1.5, 2.0)],
}


def core_signals(history: pd.DataFrame, market: Market) -> list[SignalSpec]:
    """Todas as estratégias de sinal 0/1 por moeda já testadas no projeto (universo de poucas moedas)."""
    px = wide(history, "close")
    m = daily(market)
    m = Market(*(f.reindex(index=px.index, columns=px.columns) for f in (m.close, m.high, m.low, m.volume)))

    def grid(fn_name: str) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for p in GRID_PARAMS[fn_name]:
            if fn_name == "DONCHIAN":
                sig = donchian_breakout(m, int(p["n"]))
            elif fn_name == "BOLLINGER":
                sig = bollinger_reversion(m, int(p["n"]), p["k"])
            elif fn_name == "RSI_SOBREVENDIDO":
                sig = rsi_oversold(m, p["buy_below"], p["sell_above"])
            else:
                sig = volume_breakout(m, int(p["n"]), p["k"])
            out[_label(p)] = sig.reindex_like(px).fillna(0.0)
        return out

    panic = positions_from_trades(panic_trades(history), pd.DatetimeIndex(px.index), px.columns)
    return [
        SignalSpec("TENDENCIA", "regra do painel: SMA 200 + BTC acima da SMA 200 + STOP de −20%", trend_signal(history),
                   {"sma": 200, "btc_filter": True, "stop": -0.20},
                   {"sma150": trend_signal(history, 150), "sma250": trend_signal(history, 250),
                    "sem_stop": trend_signal(history, 200, None), "stop15": trend_signal(history, 200, -0.15),
                    "stop25": trend_signal(history, 200, -0.25)}),
        SignalSpec("TENDENCIA_SEM_FILTRO", "fechamento acima da própria SMA 200, sem filtro do BTC e sem STOP",
                   trend_signal(history, 200, None, btc_filter=False), {"sma": 200},
                   {"sma150": trend_signal(history, 150, None, False), "sma250": trend_signal(history, 250, None, False)}),
        SignalSpec("TENDENCIA_BTC_SEM_STOP", "SMA 200 + filtro do BTC, sem STOP", trend_signal(history, 200, None),
                   {"sma": 200, "btc_filter": True},
                   {"sma150": trend_signal(history, 150, None), "sma250": trend_signal(history, 250, None)}),
        SignalSpec("CRUZAMENTO_50_200", "SMA 50 acima da SMA 200", _cross(px, 50, 200), {"fast": 50, "slow": 200},
                   {"40_200": _cross(px, 40, 200), "60_200": _cross(px, 60, 200), "50_150": _cross(px, 50, 150),
                    "50_250": _cross(px, 50, 250)}),
        SignalSpec("MOMENTO_90D", "retorno de 90 dias positivo", _momentum(px, 90), {"days": 90},
                   {"60d": _momentum(px, 60), "120d": _momentum(px, 120)}),
        SignalSpec("QUEDA_NA_ALTA", "compra a queda (z < −1) acima da SMA 200", _dip(px, history, -1.0), {"enter_z": -1.0},
                   {"z075": _dip(px, history, -0.75), "z125": _dip(px, history, -1.25)}),
        SignalSpec("PANICO", "regra antiga (z-score, RSI e Fear & Greed < 25), só referência", panic, requires_fng=True),
        *[SignalSpec(name, f"grade de {len(GRID_PARAMS[name])} candidatos (research/lab.py)", None, grid=grid(name))
          for name in GRID_PARAMS],
    ]
