"""Momentum relativo ao BTC com fallback em BTC ou caixa. Protocolo: docs/relative_btc_study.md (`xs-v2`). Dinheiro fictício.

    uv run python research/relative_btc_study.py
"""
from __future__ import annotations

import itertools
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cross_sectional_study as xs  # noqa: E402
from src.loaders.archive_store import read_archive_candles  # noqa: E402
from src.transformers.backtest_engine import MarketPanel, panel_from_candles  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.entry_signals import EntryRules, build_panel, trailing_return  # noqa: E402
from src.transformers.series_continuity import ContinuityRules, split_discontinuities  # noqa: E402

BTC = "BTC/USDT"
LOOKBACKS = (14, 30)
SIZES = (1, 5)
FALLBACKS = ("BTC", "caixa")


@dataclass(frozen=True)
class Spec:
    lookback: int
    k: int
    fallback: str

    @property
    def name(self) -> str:
        return f"REL L{self.lookback} top{self.k} fb={self.fallback}"


def relative_targets(tr: pd.DataFrame, member: pd.DataFrame, close: pd.DataFrame, k: int, fallback: str) -> pd.DataFrame:
    """Domingos: até k altcoins com retorno > 0 e > retorno do BTC (maior primeiro), 1/k cada; vagas vazias vão ao fallback."""
    days = [d for d in tr.index if d.weekday() == xs.REBALANCE_WEEKDAY]
    r = tr.loc[days]
    btc_r = r[BTC]
    ok = member.loc[days] & close.loc[days].notna() & r.notna()
    ok[BTC] = False
    strong = r.where(ok & r.gt(0) & r.gt(btc_r, axis=0))
    ranks = strong.rank(axis=1, ascending=False, method="first")
    picks = (ranks.le(k) & strong.notna()).astype(float) / k
    if fallback == "BTC":
        picks[BTC] = 1.0 - picks.sum(axis=1)
    return picks


def main() -> int:
    t0 = time.time()
    raw = clean_candles(read_archive_candles())
    candles, _ = split_discontinuities(raw, ContinuityRules())
    pa = build_panel(candles, EntryRules())
    keep = [c for c in pa.close.columns if bool(pa.member[c].any()) or c == BTC]
    close, member = pa.close[keep], pa.member[keep]
    mp0 = panel_from_candles(candles[candles["symbol"].isin(keep)], xs.COST)
    mp = MarketPanel(mp0.open.reindex(columns=keep), mp0.close.reindex(columns=keep), mp0.half_spread.reindex(columns=keep))
    scores = {lb: trailing_return(close, lb) for lb in LOOKBACKS}
    s90 = trailing_return(close, 90)
    ok90 = (member & s90.notna()).sum(axis=1)
    is_start = next(d for d in close.index if d.weekday() == xs.REBALANCE_WEEKDAY and ok90.loc[d] >= xs.MIN_MEMBERS)
    end = close.index.max()
    print(f"IS: {is_start:%Y-%m-%d} a {xs.IS_END:%Y-%m-%d} | OOS: {xs.OOS_START:%Y-%m-%d} a {end:%Y-%m-%d} | custo 0,25%/lado | dados até {end:%Y-%m-%d}\n")

    specs = [Spec(lb, k, fb) for lb, k, fb in itertools.product(LOOKBACKS, SIZES, FALLBACKS)]
    plans = {s: relative_targets(scores[s.lookback], member, close, s.k, s.fallback) for s in specs}
    sundays = [d for d in close.index if d.weekday() == xs.REBALANCE_WEEKDAY]
    refs = {"BTC": xs.btc_targets(close, sundays), "MERCADO": xs.market_targets(member, close, s90)}
    cols = ["config", "cagr%", "calmar", "sharpe", "maxdd%", "giro/ano", "custo%"]
    pd.set_option("display.width", 200)

    is_df = pd.DataFrame([{"config": s.name, "fb": s.fallback, "_s": s, **xs.run(mp, plans[s], is_start, xs.IS_END)} for s in specs])
    print("=== IN-SAMPLE (8 configurações; seleção só aqui) ===")
    print(is_df.sort_values("calmar", ascending=False)[cols].round(2).to_string(index=False))
    for n, t in refs.items():
        m = xs.run(mp, t, is_start, xs.IS_END)
        print(f"ref {n:8s}: cagr {m['cagr%']:.1f}%  calmar {m['calmar']:.2f}  sharpe {m['sharpe']:.2f}  maxdd {m['maxdd%']:.1f}%")
    chosen = {fb: is_df[is_df["fb"] == fb].sort_values("calmar", ascending=False).iloc[0] for fb in FALLBACKS}
    print("\nEscolhidos no IS: " + "; ".join(f"fallback {fb}: {c['config']}" for fb, c in chosen.items()))

    print("\n=== OUT-OF-SAMPLE (teste cego, avaliado uma vez) ===")
    oos_ref = {n: xs.run(mp, t, xs.OOS_START, end) for n, t in refs.items()}
    picked = {c["config"]: xs.run(mp, plans[c["_s"]], xs.OOS_START, end) for c in chosen.values()}
    table = [{"config": n, **m} for n, m in picked.items()] + [{"config": f"ref {n}", **m} for n, m in oos_ref.items()]
    print(pd.DataFrame(table)[cols + ["final"]].round(2).to_string(index=False))
    b = oos_ref["BTC"]
    for n, r in picked.items():
        ok = r["calmar"] > b["calmar"] and r["sharpe"] > b["sharpe"]
        print(f"{n}: {'PROMISSORA' if ok else 'REJEITADA'} (Calmar {r['calmar']:.2f} vs BTC {b['calmar']:.2f}; Sharpe {r['sharpe']:.2f} vs BTC {b['sharpe']:.2f})")

    print("\n=== OOS das 8 configurações (DESCRITIVO: não escolhe nada) ===")
    desc = pd.DataFrame([{"config": s.name, **xs.run(mp, plans[s], xs.OOS_START, end)} for s in specs])
    print(desc.sort_values("calmar", ascending=False)[cols + ["final"]].round(2).to_string(index=False))
    exp = {s.name: float((plans[s].loc[plans[s].index >= xs.OOS_START].drop(columns=[BTC]).sum(axis=1) > 0).mean()) for s in specs}
    print("\nFração das semanas do OOS com alguma altcoin na carteira: " + ", ".join(f"{n}: {v:.0%}" for n, v in exp.items()))
    print(f"\nconcluído em {time.time() - t0:.0f}s. Exploratório: sem IC nem correção para múltiplos testes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
