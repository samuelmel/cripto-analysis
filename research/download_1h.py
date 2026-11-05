"""Baixa candles de 1h do arquivo oficial da Binance (data.binance.vision, via host S3) para as moedas do estudo UniRenko.

Entrypoint (CLAUDE.md §1): rede e disco. Mensais até o mês passado e diários do mês corrente. Grava Parquet em
data/archive_1h/{MOEDA}_USDT.parquet. Idempotente (refaz tudo, arquivos pequenos). Arquivo ausente (404) = moeda ainda
não listada naquele mês.

    uv run python research/download_1h.py
"""
from __future__ import annotations

import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

HOST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data/spot"
COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE"]
OUT = Path("data/archive_1h")
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "tb", "tq", "ignore"]


def fetch(url: str) -> pd.DataFrame | None:
    for attempt in range(6):
        try:
            r = requests.get(url, timeout=60)
            break
        except requests.exceptions.RequestException:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)
    if r.status_code != 200:
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=COLS, skiprows=lambda i: False)
    df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()].copy()
    t = df["open_time"].astype("int64")
    unit = "us" if int(t.iloc[0]) > 10**14 else "ms"
    df["timestamp"] = pd.to_datetime(t, unit=unit, utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume", "quote_volume"]].astype(
        {"open": "float64", "high": "float64", "low": "float64", "close": "float64", "volume": "float64", "quote_volume": "float64"})


def urls(coin: str, today: date) -> list[str]:
    sym, out = f"{coin}USDT", []
    y, m = 2017, 8
    while (y, m) < (today.year, today.month):
        out.append(f"{HOST}/monthly/klines/{sym}/1h/{sym}-1h-{y}-{m:02d}.zip")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    d = today.replace(day=1)
    while d < today:  # dias fechados do mês corrente
        out.append(f"{HOST}/daily/klines/{sym}/1h/{sym}-1h-{d:%Y-%m-%d}.zip")
        d += timedelta(days=1)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    today = date.today()
    for coin in COINS:
        if (OUT / f"{coin}_USDT.parquet").exists() and "--refresh" not in sys.argv:
            continue  # já baixada (use --refresh para refazer)
        with ThreadPoolExecutor(max_workers=4) as pool:
            parts = [p for p in pool.map(fetch, urls(coin, today)) if p is not None]
        df = pd.concat(parts).drop_duplicates("timestamp").sort_values("timestamp", ignore_index=True)
        tmp = OUT / f"{coin}_USDT.parquet.tmp"
        df.to_parquet(tmp, compression="snappy", index=False)
        tmp.replace(OUT / f"{coin}_USDT.parquet")
        print(f"{coin}: {len(df)} candles 1h, {df['timestamp'].min():%Y-%m-%d} a {df['timestamp'].max():%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
