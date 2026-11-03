"""Estudo de força relativa (momentum x reversão) no universo point-in-time. Protocolo: docs/cross_sectional_study.md (`xs-v1`).

Entrypoint (CLAUDE.md §1): lê dados e imprime. Dinheiro fictício; nenhuma ordem real.

    uv run python research/cross_sectional_study.py
"""
from __future__ import annotations

import argparse
import dataclasses
import itertools
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.loaders.archive_store import read_archive_candles  # noqa: E402
from src.transformers.backtest_engine import (  # noqa: E402
    SIDE_BUY, SIDE_SELL, BacktestResult, ExecutionConfig, MarketPanel, panel_from_candles, run_backtest,
)
from src.transformers.costs import CostModel  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.entry_signals import EntryRules, build_panel, trailing_return  # noqa: E402
from src.transformers.series_continuity import ContinuityRules, split_discontinuities  # noqa: E402

LOOKBACKS = (7, 14, 30, 90)
DIRECTIONS = ("momentum", "reversao")
SIZES = (1, 5, 10)
REBALANCE_WEEKDAY = 6                      # domingo (UTC): decisão no fechamento, execução na abertura de segunda
IS_END = pd.Timestamp("2022-12-31", tz="UTC")
OOS_START = pd.Timestamp("2023-01-01", tz="UTC")
MIN_MEMBERS = 10
PER_YEAR = 365.0
COST = CostModel(fee_rate=0.001, slippage=0.0005, spread_tiers=((0.0, 0.001),))   # 0,25% por lado
CFG = ExecutionConfig(costs=COST, rebalance_band=0.0)                              # baixa por perda total (recovery 0) após 7 dias sem candle


@dataclass(frozen=True)
class Spec:
    lookback: int
    direction: str
    k: int

    @property
    def name(self) -> str:
        return f"{self.direction[:3].upper()} L{self.lookback} top{self.k}"


def weekly_targets(score: pd.DataFrame, member: pd.DataFrame, close: pd.DataFrame, direction: str, k: int) -> pd.DataFrame:
    """Pesos-alvo 1/k nos domingos: as k de maior (momentum) ou menor (reversão) retorno entre os membros com candle."""
    days = [d for d in score.index if d.weekday() == REBALANCE_WEEKDAY]
    s = score.loc[days].where(member.loc[days] & close.loc[days].notna())
    ranks = s.rank(axis=1, ascending=(direction == "reversao"), method="first")
    return (ranks.le(k) & s.notna()).astype(float) / k


def market_targets(member: pd.DataFrame, close: pd.DataFrame, score: pd.DataFrame) -> pd.DataFrame:
    days = [d for d in member.index if d.weekday() == REBALANCE_WEEKDAY]
    ok = member.loc[days] & close.loc[days].notna() & score.loc[days].notna()
    return ok.astype(float).div(ok.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def btc_targets(close: pd.DataFrame, days: list[pd.Timestamp]) -> pd.DataFrame:
    t = pd.DataFrame(0.0, index=days, columns=close.columns)
    t["BTC/USDT"] = 1.0
    return t


def metrics(res: BacktestResult) -> dict[str, float]:
    eq = res.equity
    years = len(eq) / PER_YEAR
    cagr = float(eq.iloc[-1]) ** (1 / years) - 1 if years > 0 and float(eq.iloc[-1]) > 0 else -1.0
    maxdd = float((eq / eq.cummax() - 1.0).min())
    r = res.returns
    sd = float(r.std())
    t = res.trades
    traded = float(t.loc[t["side"].isin([SIDE_BUY, SIDE_SELL]), "notional"].sum()) if len(t) else 0.0
    costs = float(t[["fee", "spread_cost", "slippage_cost"]].to_numpy().sum()) if len(t) else 0.0
    return {"cagr%": cagr * 100, "calmar": cagr / abs(maxdd) if maxdd < 0 else math.nan,
            "sharpe": float(r.mean() / sd * math.sqrt(PER_YEAR)) if sd > 0 else math.nan, "maxdd%": maxdd * 100,
            "giro/ano": traded / float(eq.mean()) / years if years > 0 else math.nan, "custo%": costs * 100,
            "final": float(eq.iloc[-1])}


def run(panel: MarketPanel, targets: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    return metrics(run_backtest(panel, targets, cfg=CFG, start=start, end=end))


def main() -> int:
    global CFG
    ap = argparse.ArgumentParser(description="Estudo xs-v1 (docs/cross_sectional_study.md)")
    ap.add_argument("--delist-recovery", type=float, default=0.0,
                    help="fração do último preço recuperada na baixa. 0 = protocolo xs-v1 (perda total); outro valor = SENSIBILIDADE pós-hoc")
    args = ap.parse_args()
    CFG = dataclasses.replace(CFG, delist_recovery=args.delist_recovery)
    t0 = time.time()
    print(f"recuperação na baixa de moeda sem candle: {args.delist_recovery:.0%}" + ("" if args.delist_recovery == 0 else "  [SENSIBILIDADE pós-hoc, fora do protocolo xs-v1]"))
    raw = clean_candles(read_archive_candles())
    candles, _ = split_discontinuities(raw, ContinuityRules())
    pa = build_panel(candles, EntryRules())
    keep = [c for c in pa.close.columns if bool(pa.member[c].any()) or c == "BTC/USDT"]
    close, member = pa.close[keep], pa.member[keep]
    mp = panel_from_candles(candles[candles["symbol"].isin(keep)], COST)
    mp = MarketPanel(mp.open.reindex(columns=keep), mp.close.reindex(columns=keep), mp.half_spread.reindex(columns=keep))
    print(f"{len(keep)} séries com passagem pelo universo; dados até {close.index.max():%Y-%m-%d}; {time.time() - t0:.0f}s", flush=True)

    scores = {lb: trailing_return(close, lb) for lb in LOOKBACKS}
    ok90 = (member & scores[90].notna()).sum(axis=1)
    is_start = next(d for d in close.index if d.weekday() == REBALANCE_WEEKDAY and ok90.loc[d] >= MIN_MEMBERS)
    end = close.index.max()
    print(f"IS: {is_start:%Y-%m-%d} a {IS_END:%Y-%m-%d} | OOS: {OOS_START:%Y-%m-%d} a {end:%Y-%m-%d} | custo 0,25%/lado\n", flush=True)

    specs = [Spec(lb, d, k) for lb, d, k in itertools.product(LOOKBACKS, DIRECTIONS, SIZES)]
    plans = {s: weekly_targets(scores[s.lookback], member, close, s.direction, s.k) for s in specs}
    refs = {"MERCADO": market_targets(member, close, scores[90]), "BTC": btc_targets(close, [d for d in close.index if d.weekday() == REBALANCE_WEEKDAY])}
    pd.set_option("display.width", 200, "display.max_rows", 200)

    is_rows = []
    for s in specs:
        is_rows.append({"config": s.name, "dir": s.direction, "_s": s, **run(mp, plans[s], is_start, IS_END)})
    ref_is = {n: run(mp, t, is_start, IS_END) for n, t in refs.items()}
    is_df = pd.DataFrame(is_rows)
    cols = ["config", "cagr%", "calmar", "sharpe", "maxdd%", "giro/ano", "custo%"]
    print("=== IN-SAMPLE (24 configurações; seleção só aqui) ===")
    print(is_df.sort_values("calmar", ascending=False)[cols].round(2).to_string(index=False))
    for n, m in ref_is.items():
        print(f"ref {n:8s}: cagr {m['cagr%']:.1f}%  calmar {m['calmar']:.2f}  sharpe {m['sharpe']:.2f}  maxdd {m['maxdd%']:.1f}%")

    chosen = {d: is_df[is_df["dir"] == d].sort_values("calmar", ascending=False).iloc[0] for d in DIRECTIONS}
    print("\nEscolhidos no IS (maior Calmar por direção): " + "; ".join(f"{d}: {c['config']}" for d, c in chosen.items()))

    print("\n=== OUT-OF-SAMPLE (teste cego, avaliado uma vez) ===")
    oos = {n: run(mp, t, OOS_START, end) for n, t in refs.items()}
    picked = {f"[{d}] {c['config']}": run(mp, plans[c["_s"]], OOS_START, end) for d, c in chosen.items()}
    table = [{"config": n, **m} for n, m in picked.items()] + [{"config": f"ref {n}", **m} for n, m in oos.items()]
    print(pd.DataFrame(table)[cols + ["final"]].round(2).to_string(index=False))
    market = oos["MERCADO"]
    for n, r in picked.items():
        ok = r["calmar"] > market["calmar"] and r["sharpe"] > market["sharpe"]
        print(f"{n}: {'PROMISSORA' if ok else 'REJEITADA'} (Calmar {r['calmar']:.2f} vs {market['calmar']:.2f}; Sharpe {r['sharpe']:.2f} vs {market['sharpe']:.2f})")

    print("\n=== OOS das 24 configurações (DESCRITIVO: não escolhe nada) ===")
    desc = pd.DataFrame([{"config": s.name, "dir": s.direction, **run(mp, plans[s], OOS_START, end)} for s in specs])
    print(desc.sort_values("calmar", ascending=False)[cols].round(2).to_string(index=False))
    g = desc.groupby("dir")[["cagr%", "calmar", "sharpe", "maxdd%"]].mean().round(2)
    print("\nMédia das 12 configurações de cada direção (OOS):")
    print(g.to_string())
    print(f"\nconcluído em {time.time() - t0:.0f}s. Exploratório: sem IC nem correção para múltiplos testes; histórico já explorado antes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
