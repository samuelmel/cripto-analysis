"""Gráfico Renko (tijolos de variação percentual fixa, escala log) do BTC com os dados salvos em data/.

Bitstamp BTC/USD (2011-2017) emendado com Binance BTC/USDT (2017 em diante). Só leitura; saída: PNG.
    uv run --with matplotlib python research/renko_chart.py [brick_pct] [saida.png]
    uv run --with matplotlib python research/renko_chart.py uni [barra_pct] [saida.png] [MOEDA] [reversao_pct]   # variante UniRenko
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


def load_ohlc(symbol: str = "BTC") -> pd.DataFrame:
    cols = ["open", "high", "low", "close"]
    if symbol != "BTC":
        return pd.read_parquet(f"data/archive/ohlcv_1d/symbol={symbol}_USDT/data.parquet").set_index("timestamp").sort_index()[cols]
    a = pd.read_parquet("data/archive_bitstamp/ohlcv_1d/symbol=BTC_USD/data.parquet").set_index("timestamp")[cols]
    b = pd.read_parquet("data/archive/ohlcv_1d/symbol=BTC_USDT/data.parquet").set_index("timestamp")[cols]
    return pd.concat([a[a.index < b.index.min()], b]).sort_index()


def unirenko(ohlc: pd.DataFrame, pct: float, rev_pct: float | None = None) -> pd.DataFrame:
    """UniRenko: cada barra abre no fechamento da anterior (sem gaps). Continuar a direção da última barra fecha a barra
    com `pct`% de movimento; reverter exige `rev_pct`% (padrão = pct) e a barra de reversão tem esse tamanho. O que passou do
    corpo vira pavio. Só há candles diários: o caminho do dia é suposto (alta = O,L,H,C; queda = O,H,L,C)."""
    up_step, dn_step = math.log(1 + pct / 100), math.log(1 + (rev_pct if rev_pct is not None else pct) / 100)
    op = math.log(float(ohlc["open"].iloc[0]))
    hi = lo = op
    direction = 0
    rows: list[dict[str, object]] = []
    for ts, r in ohlc.iterrows():
        o, h, l, c = (math.log(float(r[k])) for k in ("open", "high", "low", "close"))
        for px in ((o, l, h, c) if c >= o else (o, h, l, c)):
            hi, lo = max(hi, px), min(lo, px)
            while True:
                up_need = up_step if direction >= 0 else dn_step
                dn_need = up_step if direction <= 0 else dn_step
                if px - op >= up_need:
                    cl, direction = op + up_need, 1
                elif op - px >= dn_need:
                    cl, direction = op - dn_need, -1
                else:
                    break
                rows.append({"ts": ts, "open": op, "close": cl, "high": max(hi, op, cl), "low": min(lo, op, cl)})
                op = hi = lo = cl
    return pd.DataFrame(rows)


def main_unirenko(pct: float, out: Path, symbol: str = "BTC", rev_pct: float | None = None) -> None:
    ohlc = load_ohlc(symbol)
    bars = unirenko(ohlc, pct, rev_pct)
    fig, ax = plt.subplots(figsize=(16, 8))
    for i, r in enumerate(bars.itertuples()):
        col = "#2e9e5b" if r.close > r.open else "#d1453b"
        ax.plot([i + 0.5, i + 0.5], [math.exp(r.low), math.exp(r.high)], color=col, linewidth=0.7)
        ax.add_patch(Rectangle((i + 0.1, math.exp(min(r.open, r.close))), 0.8,
                               math.exp(max(r.open, r.close)) - math.exp(min(r.open, r.close)), facecolor=col, edgecolor=col, linewidth=0.3))
    ax.set_xlim(0, len(bars)); ax.set_yscale("log")
    ax.set_ylim(math.exp(bars["low"].min()) * 0.9, math.exp(bars["high"].max()) * 1.1)
    years = pd.DatetimeIndex(bars["ts"]).year.to_numpy()
    firsts = [i for i in range(len(bars)) if i == 0 or years[i] != years[i - 1]]
    ax.set_xticks(firsts); ax.set_xticklabels([str(years[i]) for i in firsts])  # tick no 1º bloco de cada ano (eixo atemporal)
    ax.set_title(f"{symbol} — UniRenko, tendência {pct:g}% / reversão {(rev_pct if rev_pct is not None else pct):g}% (escala log) | {len(bars)} barras | {ohlc.index[0]:%Y-%m-%d} a {ohlc.index[-1]:%Y-%m-%d}\n"
                 "abertura = fechamento anterior; pavio = excursão além do corpo; ordem intradiária suposta (só há candles diários)")
    ax.set_ylabel("Preço (US$)"); ax.grid(alpha=0.25, which="both")
    fig.tight_layout(); fig.savefig(out, dpi=130)
    print(f"{out}: {len(bars)} barras UniRenko")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "uni":
        sym = sys.argv[4].upper() if len(sys.argv) > 4 else "BTC"
        rev = float(sys.argv[5]) if len(sys.argv) > 5 else None
        main_unirenko(float(sys.argv[2]) if len(sys.argv) > 2 else 5.0, Path(sys.argv[3] if len(sys.argv) > 3 else f"unirenko_{sym.lower()}.png"), sym, rev)
        return
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
