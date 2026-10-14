"""Download em massa de klines spot do data.binance.vision (ZIPs mensais com checksum SHA-256).

Mais rápido que paginar a REST API e inclui colunas extras: quote_volume, trades, taker_buy_*.

Layout:
    data/raw/ohlcv_vision/exchange=binance/timeframe=<tf>/symbol=<SYMBOL>/year=YYYY/month=MM/data.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import logging
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pandas as pd

from storage import write_parquet

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
]
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

logger = logging.getLogger("extract_binance_vision")


def month_range(start: date, end: date) -> list[tuple[int, int]]:
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def parse_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        raw = zf.read(zf.namelist()[0])
    first = raw.split(b",", 1)[0]
    df = pd.read_csv(io.BytesIO(raw), header=0 if not first.strip().isdigit() else None)
    df.columns = COLUMNS
    df = df.drop(columns="ignore")
    for col in ("open_time", "close_time"):
        ts = df[col].astype("int64")
        # A partir de 2025-01-01 o spot vem em microssegundos.
        ts = ts.where(ts < 10**14, ts // 1000)
        df[col] = pd.to_datetime(ts, unit="ms", utc=True)
    df = df.rename(columns={"open_time": "timestamp"})
    df["trades"] = df["trades"].astype("int64")
    return df


async def fetch(session: aiohttp.ClientSession, url: str, retries: int) -> bytes | None:
    for attempt in range(1, retries + 1):
        try:
            async with session.get(url) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            wait = min(30, 2**attempt)
            logger.warning("%s falhou (tentativa %d): %s | aguardando %ss", url, attempt, exc, wait)
            await asyncio.sleep(wait)
    raise RuntimeError(f"falha após {retries} tentativas: {url}")


async def process_month(
    session: aiohttp.ClientSession, sem: asyncio.Semaphore, args: argparse.Namespace,
    symbol: str, year: int, month: int,
) -> str:
    target = (
        args.output / "exchange=binance" / f"timeframe={args.timeframe}" / f"symbol={symbol}"
        / f"year={year}" / f"month={month:02d}" / "data.parquet"
    )
    if target.exists():
        return "skip"
    name = f"{symbol}-{args.timeframe}-{year}-{month:02d}.zip"
    url = f"{BASE_URL}/{symbol}/{args.timeframe}/{name}"
    async with sem:
        content = await fetch(session, url, args.max_retries)
        if content is None:
            return "missing"
        checksum = await fetch(session, url + ".CHECKSUM", args.max_retries)
    if checksum is not None:
        expected = checksum.decode().split()[0]
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"checksum inválido: {name}")
    df = await asyncio.to_thread(parse_zip, content)
    await asyncio.to_thread(write_parquet, df, target)
    logger.info("%s %04d-%02d salvo (%d linhas)", symbol, year, month, len(df))
    return "ok"


async def run(args: argparse.Namespace) -> int:
    today = datetime.now(timezone.utc).date()
    last_full = date(today.year, today.month, 1) - timedelta(days=1)  # ZIP mensal só existe para mês fechado
    months = month_range(date(today.year - args.years, today.month, 1), last_full)

    sem = asyncio.Semaphore(args.concurrency)
    timeout = aiohttp.ClientTimeout(total=120)
    failures = 0
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for symbol in args.symbols:
            results = await asyncio.gather(
                *(process_month(session, sem, args, symbol, y, m) for y, m in months),
                return_exceptions=True,
            )
            errors = [r for r in results if isinstance(r, Exception)]
            for err in errors:
                logger.error("%s: %s", symbol, err, exc_info=err)
            failures += len(errors)
            logger.info(
                "%s concluído | novos=%d existentes=%d sem_dados=%d erros=%d", symbol,
                results.count("ok"), results.count("skip"), results.count("missing"), len(errors),
            )
    return failures


def main() -> None:
    p = argparse.ArgumentParser(description="Klines spot em massa via data.binance.vision.")
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"], help="formato BTCUSDT")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--output", type=Path, default=Path("data/raw/ohlcv_vision"))
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--log-file", type=Path, default=Path("logs/extract_binance_vision.log"))
    args = p.parse_args()

    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=args.log_level.upper(), format=LOG_FORMAT, force=True,
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(args.log_file, encoding="utf-8")],
    )
    sys.exit(1 if asyncio.run(run(args)) else 0)


if __name__ == "__main__":
    main()
