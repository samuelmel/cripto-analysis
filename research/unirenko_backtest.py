"""Backtest EXPLORATÓRIO de uma regra em barras UniRenko (dinheiro fictício, sem ordens reais).

Regra (fixada aqui antes de ver resultado): compra depois que `lag` barras de alta SEGUEM a barra de reversão (lag=0: na
própria reversão; lag=2: duas barras à frente, esperando a curva se formar); vende quando uma barra de baixa fecha. A
barra fecha no dia D; a ordem é executada na ABERTURA de D+1 (sem olhar o futuro), com 0,25% por operação (taxa+spread+slippage).
Limite: candles diários, então a ordem intradiária dentro do dia é suposta ao montar as barras.

    uv run --with matplotlib python research/unirenko_backtest.py   # precisa de data/archive_1h (research/download_1h.py)
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
    """Posição (0/1) ao FIM de cada candle (dia ou hora), dada a sequência de barras fechadas até ele."""
    pos = pd.Series(0.0, index=index)
    day_of = pd.DatetimeIndex(bars["ts"])
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


def stats(ret: pd.Series, per_year: float) -> dict[str, float]:
    eq = (1 + ret).cumprod()
    years = len(ret) / per_year
    sd = float(ret.std())
    cagr = float(eq.iloc[-1]) ** (1 / years) - 1
    maxdd = float((eq / eq.cummax() - 1).min())
    return {"cagr": cagr, "sharpe": float(ret.mean() / sd * math.sqrt(per_year)) if sd > 0 else math.nan,
            "maxdd": maxdd, "calmar": cagr / abs(maxdd) if maxdd < 0 else math.nan, "total": float(eq.iloc[-1]) - 1}


def load(symbol: str, res: str) -> pd.DataFrame:
    """OHLC diário (Binance 1d, ordem intradiária suposta) ou de 1h (data/archive_1h), na MESMA janela (a do 1h)."""
    h = pd.read_parquet(f"data/archive_1h/{symbol}_USDT.parquet").set_index("timestamp").sort_index()[["open", "high", "low", "close"]]
    if res == "1h":
        return h
    d = pd.read_parquet(f"data/archive/ohlcv_1d/symbol={symbol}_USDT/data.parquet").set_index("timestamp").sort_index()[["open", "high", "low", "close"]]
    return d[(d.index >= h.index.min().normalize()) & (d.index <= h.index.max())]


def run(symbol: str, res: str, trend: float, rev: float, lag: int) -> tuple[dict[str, float], dict[str, float], float, int]:
    ohlc = load(symbol, res)
    per_year = 365.25 * (24 if res == "1h" else 1)
    bars = unirenko(ohlc, trend, rev)
    pos = positions(bars, pd.DatetimeIndex(ohlc.index), lag)
    oo = ohlc["open"].shift(-1) / ohlc["open"] - 1          # retorno abertura(t) -> abertura(t+1)
    held = pos.shift(1).fillna(0.0)                          # decidido no fechamento de t-1, executa na abertura de t
    ret = (held * oo).iloc[:-1].fillna(0.0)
    ret = ret - held.diff().abs().fillna(0.0).iloc[:-1] * COST
    bh = oo.iloc[:-1].fillna(0.0)
    return stats(ret, per_year), stats(bh, per_year), float(held.mean()), int(held.diff().abs().sum() / 2)


def main() -> None:
    rows = []
    for sym in COINS:
        for res in ("1h", "1d"):
            for rev in (10, 15, 20):
                for lag in (0, 1):
                    s, b, expo, trades = run(sym, res, 10, rev, lag)
                    rows.append({"moeda": sym, "dados": res, "rev": rev, "lag": lag, "cagr%": s["cagr"] * 100, "calmar": s["calmar"], "sharpe": s["sharpe"],
                                 "maxdd%": s["maxdd"] * 100, "bh_cagr%": b["cagr"] * 100, "bh_calmar": b["calmar"], "bh_sharpe": b["sharpe"],
                                 "bh_maxdd%": b["maxdd"] * 100, "expo%": expo * 100, "ops": trades})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220, "display.max_rows", 300)
    print(df[df["dados"] == "1h"].round(2).to_string(index=False))
    cols = ["cagr%", "calmar", "sharpe", "maxdd%", "bh_cagr%", "bh_calmar", "bh_sharpe", "bh_maxdd%", "expo%", "ops"]
    print("\nMédia entre as 7 moedas, 1h (ordem real) vs 1d (ordem suposta), mesma janela:")
    print(df.groupby(["dados", "rev", "lag"])[cols].mean().round(2).to_string())
    df["bate_calmar"] = df["calmar"] > df["bh_calmar"]
    df["bate_sharpe"] = df["sharpe"] > df["bh_sharpe"]
    print("\nFração das 7 moedas em que a regra bate comprar-e-segurar:")
    print(df.groupby(["dados", "rev", "lag"])[["bate_calmar", "bate_sharpe"]].mean().round(2).to_string())


if __name__ == "__main__":
    main()
