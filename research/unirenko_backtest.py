"""Backtest EXPLORATÓRIO de uma regra em barras UniRenko (dinheiro fictício, sem ordens reais).

Regra (fixada aqui antes de ver resultado): compra depois que `lag` barras de alta SEGUEM a barra de reversão (lag=0: na
própria reversão; lag=2: duas barras à frente, esperando a curva se formar); vende quando uma barra de baixa fecha. A
barra fecha no dia D; a ordem é executada na ABERTURA de D+1 (sem olhar o futuro), com 0,25% por operação (taxa+spread+slippage).
Limite: candles diários, então a ordem intradiária dentro do dia é suposta ao montar as barras.

    uv run --with matplotlib python research/unirenko_backtest.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from renko_chart import load_ohlc, unirenko  # noqa: E402

COST = 0.0025
COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE"]


def positions(bars: pd.DataFrame, index: pd.DatetimeIndex, lag: int) -> pd.Series:
    """Posição (0/1) ao FIM de cada dia, dada a sequência de barras fechadas até aquele dia."""
    pos = pd.Series(0.0, index=index)
    day_of = pd.DatetimeIndex(bars["ts"]).normalize()
    run, long = 0, False
    by_day = {d: g for d, g in bars.groupby(day_of)}
    for d in index:
        for r in by_day.get(d, pd.DataFrame()).itertuples():
            if r.close > r.open:
                run += 1
                if run >= lag + 1:
                    long = True
            else:
                run, long = 0, False
        pos.loc[d] = float(long)
    return pos


def stats(ret: pd.Series) -> dict[str, float]:
    eq = (1 + ret).cumprod()
    years = len(ret) / 365.25
    sd = float(ret.std())
    return {"cagr": float(eq.iloc[-1]) ** (1 / years) - 1, "sharpe": float(ret.mean() / sd * math.sqrt(365)) if sd > 0 else math.nan,
            "maxdd": float((eq / eq.cummax() - 1).min()), "total": float(eq.iloc[-1]) - 1}


def run(symbol: str, trend: float, rev: float, lag: int) -> tuple[dict[str, float], dict[str, float], float, int]:
    ohlc = load_ohlc(symbol)
    ohlc.index = ohlc.index.normalize()
    bars = unirenko(ohlc, trend, rev)
    pos = positions(bars, pd.DatetimeIndex(ohlc.index), lag)
    oo = ohlc["open"].shift(-1) / ohlc["open"] - 1          # retorno abertura(t) -> abertura(t+1)
    held = pos.shift(1).fillna(0.0)                          # decidido no fechamento de t-1, executa na abertura de t
    ret = (held * oo.shift(0)).iloc[:-1].fillna(0.0)
    ret = ret - held.diff().abs().fillna(0.0).iloc[:-1] * COST
    bh = oo.iloc[:-1].fillna(0.0)
    return stats(ret), stats(bh), float(held.mean()), int(held.diff().abs().sum() / 2)


def main() -> None:
    rows = []
    for sym in COINS:
        for trend, rev in ((10, 10), (10, 15), (10, 20)):
            for lag in (0, 1, 2):
                s, b, expo, trades = run(sym, trend, rev, lag)
                rows.append({"moeda": sym, "rev": rev, "lag": lag, "cagr%": s["cagr"] * 100, "sharpe": s["sharpe"], "maxdd%": s["maxdd"] * 100,
                             "bh_cagr%": b["cagr"] * 100, "bh_sharpe": b["sharpe"], "bh_maxdd%": b["maxdd"] * 100, "expo%": expo * 100, "ops": trades})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200, "display.max_rows", 200)
    print(df.round(2).to_string(index=False))
    print("\nMédia entre moedas por (rev, lag):")
    g = df.groupby(["rev", "lag"])[["cagr%", "sharpe", "maxdd%", "bh_cagr%", "bh_sharpe", "bh_maxdd%"]].mean().round(2)
    print(g.to_string())
    print("\nFração das 7 moedas com Sharpe da regra > Sharpe do comprar-e-segurar:")
    df["bate"] = df["sharpe"] > df["bh_sharpe"]
    print(df.groupby(["rev", "lag"])["bate"].mean().round(2).to_string())


if __name__ == "__main__":
    main()
