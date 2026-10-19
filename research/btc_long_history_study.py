"""Regra SMA 200 no BTC com o histórico da Bitstamp (2011–2017). Protocolo: docs/btc_long_history.md (fixado antes).

Entrypoint (CLAUDE.md §1): lê `data/archive_bitstamp` (restaurada da branch base-pesquisa), chama funções puras do
catálogo de estratégias, do motor único, das métricas e do bootstrap, e grava `evidence/btc_long_history/`.

    git fetch origin base-pesquisa && git archive origin/base-pesquisa | tar -x -C data/
    uv run python research/btc_long_history_study.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.signal_evidence_study import git_state  # noqa: E402
from src.loaders.archive_store import read_archive_candles  # noqa: E402
from src.loaders.market_store import read_ohlcv  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.backtest_engine import ExecutionConfig, MarketPanel, panel_from_candles, run_backtest  # noqa: E402
from src.transformers.bootstrap import BootstrapConfig, bootstrap_difference, make_resampler, sharpe_stat  # noqa: E402
from src.transformers.costs import CostModel  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.metrics import engine_metrics  # noqa: E402
from src.transformers.policy_evaluation import data_fingerprint  # noqa: E402
from src.transformers.portfolio_backtest import checked  # noqa: E402
from src.transformers.series_continuity import ContinuityRules, split_discontinuities  # noqa: E402
from src.transformers.strategy_catalog import trend_signal  # noqa: E402

BITSTAMP_DIR = Path("data/archive_bitstamp")
OUT_DIR = Path("evidence/btc_long_history")
SYMBOL = "BTC/USD"
NEW_END = pd.Timestamp("2017-08-16", tz="UTC")
BOOT = BootstrapConfig(n_boot=2000, seed=20261019, ci_level=0.90)
CYCLES = {"2011-2013": ("2011-01-01", "2013-12-31"), "2014-2015": ("2014-01-01", "2015-12-31"),
          "2016-2017": ("2016-01-01", "2017-08-16")}


def run(panel: MarketPanel, target: pd.DataFrame, cfg: ExecutionConfig, start: pd.Timestamp, end: pd.Timestamp, label: str) -> pd.Series:
    res = checked(run_backtest(panel, target, cfg=cfg, start=start, end=end), label)
    return res.returns


def summarize(panel: MarketPanel, target: pd.DataFrame, cfg: ExecutionConfig, start: pd.Timestamp, end: pd.Timestamp, label: str) -> dict[str, object]:
    res = checked(run_backtest(panel, target, cfg=cfg, start=start, end=end), label)
    return {"label": label, **engine_metrics(res)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raw = read_archive_candles([SYMBOL], BITSTAMP_DIR) if (BITSTAMP_DIR / "ohlcv_1d").is_dir() else read_ohlcv([SYMBOL], BITSTAMP_DIR)
    if raw.empty:
        print("data/archive_bitstamp vazio: restaure a branch base-pesquisa (ver docstring)", file=sys.stderr)
        return 1
    clean = clean_candles(raw)
    candles, _ = split_discontinuities(clean, ContinuityRules())
    days = pd.date_range(candles["timestamp"].min(), candles["timestamp"].max(), freq="D", tz="UTC")
    quality = {"first": str(candles["timestamp"].min().date()), "last": str(candles["timestamp"].max().date()),
               "candles": len(candles), "missing_days": int(len(days) - candles["timestamp"].nunique()),
               "zero_volume_days": int(candles["volume"].le(0).sum()), "series": int(candles["symbol"].nunique())}
    print("dados:", quality)
    btc = candles.assign(symbol=SYMBOL)
    panel = panel_from_candles(btc, CostModel())
    history = btc[["symbol", "timestamp", "close"]].copy()
    signal = trend_signal(history, regime_symbol=SYMBOL)
    hold = pd.DataFrame(1.0, index=signal.index, columns=signal.columns)
    sma_ready = history["close"].rolling(200, min_periods=200).mean().notna().to_numpy()
    first = pd.Timestamp(history["timestamp"].to_numpy()[np.argmax(sma_ready)])
    start = first + pd.Timedelta(days=1)
    cfg = ExecutionConfig(costs=CostModel(), rebalance_band=0.0)

    # ---- hipótese H1: período inédito (2011–2017) --------------------------------------------------------
    r = run(panel, signal, cfg, start, NEW_END, "regra")
    b = run(panel, hold, cfg, start, NEW_END, "comprar e segurar")
    x, y = r.to_numpy("float64"), b.to_numpy("float64")
    est = bootstrap_difference(x, y, sharpe_stat(), make_resampler([x, y], BOOT))
    if est.estimate > 0 and est.p_value < 0.05 and est.ci_low > 0:
        verdict = "CONFIRMADA"
    elif est.estimate > 0:
        verdict = "COMPATIVEL_COM_SORTE"
    else:
        verdict = "NEGATIVA"
    h1 = pd.DataFrame([{"start": start, "end": NEW_END, "n_days": len(x), "delta_sharpe": est.estimate,
                        "ci_low": est.ci_low, "ci_high": est.ci_high, "p_value": est.p_value, "block": est.block,
                        "verdict": verdict}])

    # ---- descritivo ---------------------------------------------------------------------------------------
    rows = [summarize(panel, signal, cfg, start, NEW_END, "regra 2011-2017"),
            summarize(panel, hold, cfg, start, NEW_END, "comprar e segurar 2011-2017")]
    for name, (a, z) in CYCLES.items():
        s, e = max(start, pd.Timestamp(a, tz="UTC")), pd.Timestamp(z, tz="UTC")
        rows.append(summarize(panel, signal, cfg, s, e, f"regra {name}"))
        rows.append(summarize(panel, hold, cfg, s, e, f"comprar e segurar {name}"))
    variants = {"sma150": trend_signal(history, 150, regime_symbol=SYMBOL),
                "sma250": trend_signal(history, 250, regime_symbol=SYMBOL),
                "sem_stop": trend_signal(history, 200, None, regime_symbol=SYMBOL)}
    high_fee = ExecutionConfig(costs=CostModel(fee_rate=0.005), rebalance_band=0.0)
    sens = []
    for name, sig in variants.items():
        rv = run(panel, sig, cfg, start, NEW_END, name)
        sens.append({"variant": name, "delta_sharpe": float(sharpe_stat()(rv.to_numpy("float64")[None, :])[0] - sharpe_stat()(y[None, :])[0])})
    rf = run(panel, signal, high_fee, start, NEW_END, "taxa 0,5%")
    bf = run(panel, hold, high_fee, start, NEW_END, "taxa 0,5% hold")
    sens.append({"variant": "taxa_0.5pct", "delta_sharpe": float(sharpe_stat()(rf.to_numpy("float64")[None, :])[0] - sharpe_stat()(bf.to_numpy("float64")[None, :])[0])})

    fp = data_fingerprint(candles)
    head, dirty = git_state()
    meta = {"data_fingerprint": fp, "code_version": head, "dirty": dirty, **quality}
    for name, table in (("h1", h1), ("descritivo", pd.DataFrame(rows)), ("sensibilidade", pd.DataFrame(sens))):
        write_parquet(table.assign(**{k: str(v) for k, v in meta.items()}), OUT_DIR / f"{name}.parquet")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"\ncódigo {head[:10]}{' (árvore com alterações)' if dirty else ''} · dados {fp[:12]}")
    print("\nH1 (2011–2017, período inédito):\n" + h1.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    cols = ["label", "n_obs", "total_return_pct", "cagr_pct", "sharpe", "max_drawdown_pct", "max_drawdown_days", "exposure_pct", "n_entries", "cost_pct"]
    print("\n" + pd.DataFrame(rows)[cols].round(2).to_string(index=False))
    print("\nsensibilidade (ΔSharpe):\n" + pd.DataFrame(sens).round(3).to_string(index=False))
    if not math.isfinite(est.estimate):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
