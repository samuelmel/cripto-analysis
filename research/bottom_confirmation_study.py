"""Fundo confirmado por 2 candles x acaso. Protocolo: docs/fundo_confirmado.md (fixado antes).

Entrypoint (CLAUDE.md §1): lê os candles diários salvos, chama as funções puras de `bottom_confirmation` e grava
Parquet em `evidence/bottom_confirmation/`.

    uv run python research/bottom_confirmation_study.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.loaders.market_store import MARKET_DIR, read_ohlcv  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.bottom_confirmation import all_trades, evaluate  # noqa: E402

OUT_DIR = Path("evidence/bottom_confirmation")


def load_daily() -> pd.DataFrame:
    folders = sorted((MARKET_DIR / "ohlcv_1d").glob("symbol=*"))
    symbols = [f.name[len("symbol="):].replace("_", "/") for f in folders]
    candles = read_ohlcv(symbols)
    if candles.empty:
        raise SystemExit("sem candles diários em data/market/ohlcv_1d")
    return candles[["timestamp", "symbol", "open", "close"]].dropna().reset_index(drop=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    candles = load_daily()
    trades = all_trades(candles)
    results = evaluate(trades)
    write_parquet(trades.astype({"symbol": "string"}), OUT_DIR / "trades.parquet")
    write_parquet(results, OUT_DIR / "results.parquet")
    print(f"{candles['symbol'].nunique()} moedas, dados até {candles['timestamp'].max():%Y-%m-%d}, {len(trades)} operações")
    pd.set_option("display.width", 220)
    show = results.copy()
    for col in ("mean_return", "mean_random", "mean_excess", "ci_low", "ci_high"):
        show[col] = (show[col] * 100).round(2)
    print(show.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
