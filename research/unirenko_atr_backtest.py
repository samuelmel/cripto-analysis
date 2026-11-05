"""UniRenko com bloco dinâmico por ATR: exploração mecânica (dinheiro fictício, sem ordens reais). Fixado ANTES de rodar.

Construção (candles de 1h, ordem intradiária real do arquivo da Binance):
    tendência  bloco = ATR(n) diário em % do fechamento (n = 14 ou 20), com o ATR do dia ANTERIOR já fechado (sem olhar o futuro)
    reversão   k × ATR com k = 1,5 ou 2
    lag        0 (compra na barra de reversão para cima); vende quando fecha uma barra de baixa
    execução   barra fecha no candle t, ordem na abertura do candle t+1; 0,25% por operação
Critério de parada combinado com o usuário: se a regra não superar comprar-e-segurar em Calmar OU em Sharpe em pelo menos
50% dos testes (7 moedas × 4 configurações = 28), o eixo Renko é encerrado, mesmo sem teste estatístico.

    uv run --with matplotlib python research/unirenko_atr_backtest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from renko_chart import unirenko  # noqa: E402
from unirenko_backtest import COINS, COST, load, positions, stats  # noqa: E402

PER_YEAR = 365.25 * 24


def atr_pct(hourly: pd.DataFrame, n: int) -> pd.Series:
    """ATR(n) diário (média simples do true range) em % do fechamento, deslocado 1 dia (usa só dias já fechados)."""
    d = hourly.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    pct = (tr.rolling(n).mean() / d["close"] * 100.0).shift(1)
    return pct.bfill()


def run(symbol: str, n: int, k_rev: float) -> dict[str, float]:
    h = load(symbol, "1h")
    a = atr_pct(h, n)
    bars = unirenko(h, a, a * k_rev)
    pos = positions(bars, pd.DatetimeIndex(h.index), 0)
    oo = h["open"].shift(-1) / h["open"] - 1
    held = pos.shift(1).fillna(0.0)
    ret = (held * oo).iloc[:-1].fillna(0.0) - held.diff().abs().fillna(0.0).iloc[:-1] * COST
    s, b = stats(ret, PER_YEAR), stats(oo.iloc[:-1].fillna(0.0), PER_YEAR)
    return {"moeda": symbol, "atr": n, "k_rev": k_rev, "bloco%": float(a.median()), "barras": len(bars), "cagr%": s["cagr"] * 100, "calmar": s["calmar"],
            "sharpe": s["sharpe"], "maxdd%": s["maxdd"] * 100, "bh_cagr%": b["cagr"] * 100, "bh_calmar": b["calmar"], "bh_sharpe": b["sharpe"],
            "bh_maxdd%": b["maxdd"] * 100, "expo%": float(held.mean()) * 100, "ops": int(held.diff().abs().sum() / 2)}


def main() -> None:
    df = pd.DataFrame([run(c, n, k) for c in COINS for n in (14, 20) for k in (1.5, 2.0)])
    df["bate_calmar"], df["bate_sharpe"] = df["calmar"] > df["bh_calmar"], df["sharpe"] > df["bh_sharpe"]
    pd.set_option("display.width", 220, "display.max_rows", 100)
    print(df.drop(columns=["bate_calmar", "bate_sharpe"]).round(2).to_string(index=False))
    cols = ["bloco%", "barras", "cagr%", "calmar", "sharpe", "maxdd%", "bh_calmar", "bh_sharpe", "bh_maxdd%", "expo%", "ops", "bate_calmar", "bate_sharpe"]
    print("\nMédia por configuração:")
    print(df.groupby(["atr", "k_rev"])[cols].mean().round(2).to_string())
    print(f"\nTotal (28 testes): bate em Calmar {df['bate_calmar'].mean():.0%}, bate em Sharpe {df['bate_sharpe'].mean():.0%}")
    print("Critério (>= 50% em Calmar OU Sharpe):", "ATENDIDO" if max(df["bate_calmar"].mean(), df["bate_sharpe"].mean()) >= 0.5 else "NÃO ATENDIDO")


if __name__ == "__main__":
    main()
