"""Smart DCA x DCA fixo com aporte mensal e caixa finito. Protocolo: docs/dca_study.md (`dca-v1`). Dinheiro fictício.

    uv run python research/dca_study.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COST = 0.0025
C = 1.0                                   # aporte mensal
WEEK_LOT = 12 * C / 52                    # lote semanal do DCA fixo
THRESHOLDS = ((-0.40, 5.0), (-0.20, 3.0)) # dd <= limiar -> multiplicador (verificado do mais fundo ao mais raso)
PRIMARY_F = 0.5
SENSITIVITY_F = (0.25, 0.75)
HORIZONS = (3, 5)


def load(asset: str) -> pd.DataFrame:
    cols = ["open", "close"]
    if asset == "BTC":
        a = pd.read_parquet("data/archive_bitstamp/ohlcv_1d/symbol=BTC_USD/data.parquet").set_index("timestamp")[cols]
        b = pd.read_parquet("data/archive/ohlcv_1d/symbol=BTC_USDT/data.parquet").set_index("timestamp")[cols]
        df = pd.concat([a[a.index < b.index.min()], b])
    else:
        df = pd.read_parquet(f"data/archive/ohlcv_1d/symbol={asset}_USDT/data.parquet").set_index("timestamp")[cols]
    return pd.DataFrame(df.sort_index())


def multiplier(dd: float) -> float:
    for limit, m in THRESHOLDS:
        if dd <= limit:
            return m
    return 1.0


@dataclass(frozen=True)
class Outcome:
    value_per_real: float
    avg_cost: float
    deployed: float          # fração do aportado que virou ativo
    idle: float              # caixa médio / patrimônio
    maxdd: float             # pior queda de patrimônio / aportado acumulado


def simulate(df: pd.DataFrame, ath: pd.Series, start: pd.Timestamp, end: pd.Timestamp, f: float | None) -> Outcome:
    """f=None: DCA fixo. f=x: Smart DCA com lote-base x*L."""
    idx = df.index[(df.index >= start) & (df.index <= end)]
    open_, close = df["open"].reindex(idx).to_numpy(), df["close"].reindex(idx).to_numpy()
    cash = units = spent = contributed = 0.0
    pending = 0.0
    ratio: list[float] = []
    idle: list[float] = []
    for i, d in enumerate(idx):
        if pending > 0:                                            # compra decidida no fechamento anterior: abertura de hoje
            spend = min(pending, cash)
            units += spend / (open_[i] * (1 + COST))
            cash -= spend
            spent += spend
            pending = 0.0
        if d.day == 1:
            cash += C
            contributed += C
        equity = cash + units * close[i]
        ratio.append(equity / contributed)
        idle.append(cash / equity if equity > 0 else 0.0)
        if d.weekday() == 6 and i + 1 < len(idx):                  # domingo: decide com dados até o fechamento
            if f is None:
                pending = WEEK_LOT
            else:
                dd = close[i] / float(ath.loc[d]) - 1.0
                pending = multiplier(dd) * f * WEEK_LOT
    r = np.array(ratio)
    final = cash + units * close[-1]
    return Outcome(final / contributed, spent / (units * 1.0) if units > 0 else float("nan"), spent / contributed,
                   float(np.mean(idle)), float((r / np.maximum.accumulate(r) - 1.0).min()))


def windows(df: pd.DataFrame, first_year: int, years: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    out = []
    for y in range(first_year, df.index.max().year + 1):
        for m in (1, 7):
            s = pd.Timestamp(year=y, month=m, day=1, tz="UTC")
            e = s + pd.DateOffset(years=years) - pd.Timedelta(days=1)
            if s >= df.index.min() and e <= df.index.max():
                out.append((s, e))
    return out


def run_asset(asset: str, first_year: int) -> None:
    df = load(asset)
    ath = df["close"].cummax()
    print(f"\n########## {asset}: {df.index.min():%Y-%m-%d} a {df.index.max():%Y-%m-%d} ##########")
    verdict = {}
    for years in HORIZONS:
        wins = windows(df, first_year, years)
        rows = []
        for s, e in wins:
            fixed = simulate(df, ath, s, e, None)
            row: dict[str, object] = {"inicio": f"{s:%Y-%m}", "fixo": fixed.value_per_real}
            for f in (PRIMARY_F, *SENSITIVITY_F):
                o = simulate(df, ath, s, e, f)
                row[f"f{f}"], row[f"dif{f}%"] = o.value_per_real, (o.value_per_real / fixed.value_per_real - 1) * 100
                if f == PRIMARY_F:
                    row["resultado"] = "VITORIA" if o.value_per_real > fixed.value_per_real else "derrota"
                    row["investido%"], row["ocioso%"], row["avg_cost_ratio"] = o.deployed * 100, o.idle * 100, o.avg_cost / fixed.avg_cost
                    row["maxdd_smart%"], row["maxdd_fixo%"] = o.maxdd * 100, fixed.maxdd * 100
            rows.append(row)
        df_w = pd.DataFrame(rows)
        pd.set_option("display.width", 250, "display.max_columns", 40)
        print(f"\n--- {asset}, janelas de {years} anos (f=0,5 principal) ---")
        show = ["inicio", "fixo", "f0.5", "dif0.5%", "resultado", "investido%", "ocioso%", "avg_cost_ratio", "maxdd_smart%", "maxdd_fixo%"]
        print(df_w[show].round(3).to_string(index=False))
        for f in (PRIMARY_F, *SENSITIVITY_F):
            d = df_w[f"dif{f}%"]
            print(f"  f={f}: vitórias {int((d > 0).sum())}/{len(d)} ({(d > 0).mean():.0%}); diferença média {d.mean():+.2f}%, mediana {d.median():+.2f}%, pior {d.min():+.2f}%, melhor {d.max():+.2f}%")
        verdict[years] = (float((df_w[f"dif{PRIMARY_F}%"] > 0).mean()), float(df_w[f"dif{PRIMARY_F}%"].mean()), len(df_w))
    ok = all(v[0] > 0.60 and v[1] > 0 for v in verdict.values())
    print(f"\n>>> {asset}: {'PROMISSOR' if ok else 'REJEITADO'} (critério: >60% de vitórias nos dois horizontes e diferença média > 0): "
          + "; ".join(f"{y}a: {v[0]:.0%} de {v[2]} janelas, média {v[1]:+.2f}%" for y, v in verdict.items()))


def main() -> int:
    run_asset("BTC", 2012)
    run_asset("ETH", 2018)
    print("\nExploratório: um caminho de preços por ativo, janelas sobrepostas, sem IC.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
