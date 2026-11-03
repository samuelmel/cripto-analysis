"""Gráfico Renko (tijolos de variação percentual fixa, escala log) do BTC com os dados salvos em data/.

Bitstamp BTC/USD (2011-2017) emendado com Binance BTC/USDT (2017 em diante). Só leitura; saída: PNG.
    uv run --with matplotlib python research/renko_chart.py [brick_pct] [saida.png]
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402


def load_btc() -> pd.Series:
    a = pd.read_parquet("data/archive_bitstamp/ohlcv_1d/symbol=BTC_USD/data.parquet").set_index("timestamp")["close"]
    b = pd.read_parquet("data/archive/ohlcv_1d/symbol=BTC_USDT/data.parquet").set_index("timestamp")["close"]
    return pd.concat([a[a.index < b.index.min()], b]).sort_index()


def renko(close: pd.Series, pct: float) -> list[tuple[pd.Timestamp, float, float]]:
    """Tijolos (data, base, topo); sobe/desce um tijolo a cada `pct`% de variação sobre o último tijolo; reversão = 2 tijolos."""
    step = math.log(1 + pct / 100)
    ref = math.log(float(close.iloc[0]))
    bricks: list[tuple[pd.Timestamp, float, float]] = []
    direction = 0
    for ts, px in close.items():
        lp = math.log(float(px))
        while True:
            if direction >= 0 and lp >= ref + step:
                bricks.append((ts, ref, ref + step)); ref += step; direction = 1
            elif direction <= 0 and lp <= ref - step:
                bricks.append((ts, ref, ref - step)); ref -= step; direction = -1
            elif direction == 1 and lp <= ref - 2 * step:
                bricks.append((ts, ref - step, ref - 2 * step)); ref -= 2 * step; direction = -1
            elif direction == -1 and lp >= ref + 2 * step:
                bricks.append((ts, ref + step, ref + 2 * step)); ref += 2 * step; direction = 1
            else:
                break
    return bricks


def main() -> None:
    pct = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "renko_btc.png")
    close = load_btc()
    bricks = renko(close, pct)
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={"height_ratios": [3, 1]})
    for i, (_, lo, hi) in enumerate(bricks):
        up = hi > lo
        ax.add_patch(Rectangle((i, math.exp(min(lo, hi))), 1, math.exp(max(lo, hi)) - math.exp(min(lo, hi)),
                               facecolor="#2e9e5b" if up else "#d1453b", edgecolor="white", linewidth=0.3))
    ax.set_xlim(0, len(bricks)); ax.set_yscale("log")
    ax.set_ylim(min(math.exp(min(b[1], b[2])) for b in bricks) * 0.9, max(math.exp(max(b[1], b[2])) for b in bricks) * 1.1)
    n = max(1, len(bricks) // 12)
    ax.set_xticks(range(0, len(bricks), n)); ax.set_xticklabels([bricks[i][0].strftime("%Y-%m") for i in range(0, len(bricks), n)])
    ax.set_title(f"BTC — Renko, tijolo de {pct:g}% (escala log) | {len(bricks)} tijolos | {close.index[0]:%Y-%m-%d} a {close.index[-1]:%Y-%m-%d}")
    ax.set_ylabel("Preço (US$)"); ax.grid(alpha=0.25, which="both")
    ax2.plot(close.index, close.values, color="#555", linewidth=0.8); ax2.set_yscale("log"); ax2.grid(alpha=0.25)
    ax2.set_title("Fechamento diário (referência)")
    fig.tight_layout(); fig.savefig(out, dpi=130)
    print(f"{out}: {len(bricks)} tijolos; último {bricks[-1][0]:%Y-%m-%d} {'alta' if bricks[-1][2] > bricks[-1][1] else 'queda'}")


if __name__ == "__main__":
    main()
