"""Dados de contexto de mercado além do OHLCV.

Subcomandos:
    fng        Crypto Fear & Greed Index diário (alternative.me, histórico completo, sem chave)
    funding    Funding rate de perpétuos USDⓈ-M da Binance (histórico completo, sem chave)
    coingecko  Preço, market cap e volume total diários (CoinGecko Demo: últimos 365 dias;
               chave gratuita opcional em COINGECKO_API_KEY)

Layout:
    data/raw/fear_greed/data.parquet
    data/raw/funding_rate/symbol=<SYMBOL>/year=YYYY/month=MM/data.parquet
    data/raw/coingecko/coin_id=<id>/data.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import aiohttp
import pandas as pd

from storage import write_by_month, write_parquet

FNG_URL = "https://api.alternative.me/fng/"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
FUNDING_START_MS = 1_567_296_000_000  # 2019-09-01, início dos perpétuos USDⓈ-M
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

logger = logging.getLogger("extract_market_context")


async def get_json(session: aiohttp.ClientSession, url: str, params: dict, retries: int = 5):
    for attempt in range(1, retries + 1):
        try:
            async with session.get(url, params=params) as resp:
                if resp.status in (418, 429):
                    wait = int(resp.headers.get("Retry-After", 2**attempt))
                    logger.warning("%s rate limit (HTTP %d) | aguardando %ss", url, resp.status, wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            wait = min(30, 2**attempt)
            logger.warning("%s falhou (tentativa %d): %s | aguardando %ss", url, attempt, exc, wait)
            await asyncio.sleep(wait)
    raise RuntimeError(f"falha após {retries} tentativas: {url}")


async def extract_fng(session: aiohttp.ClientSession, out: Path) -> None:
    payload = await get_json(session, FNG_URL, {"limit": 0, "format": "json"})
    df = pd.DataFrame(payload["data"])
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(df["timestamp"].astype("int64"), unit="s", utc=True),
        "value": df["value"].astype("int16"),
        "classification": df["value_classification"],
    }).sort_values("timestamp")
    write_parquet(df, out / "fear_greed" / "data.parquet")
    logger.info("fear & greed salvo: %d dias (%s → %s)", len(df), df.timestamp.min().date(), df.timestamp.max().date())


async def extract_funding(session: aiohttp.ClientSession, out: Path, symbols: list[str]) -> None:
    for symbol in symbols:
        rows, start = [], FUNDING_START_MS
        while True:
            page = await get_json(session, FUNDING_URL, {"symbol": symbol, "startTime": start, "limit": 1000})
            if not page:
                break
            rows.extend(page)
            if len(page) < 1000:
                break
            start = page[-1]["fundingTime"] + 1
            await asyncio.sleep(0.7)  # limite compartilhado de 500 req / 5 min por IP
        if not rows:
            logger.error("%s: sem funding rate (símbolo não listado em USDⓈ-M?)", symbol)
            continue
        df = pd.DataFrame(rows)
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(df["fundingTime"], unit="ms", utc=True),
            "funding_rate": df["fundingRate"].astype("float64"),
            "mark_price": pd.to_numeric(df["markPrice"], errors="coerce") if "markPrice" in df else float("nan"),
        }).drop_duplicates("timestamp").sort_values("timestamp")
        parts = write_by_month(df, out / "funding_rate" / f"symbol={symbol}")
        logger.info("%s funding salvo: %d registros em %d partições", symbol, len(df), parts)


async def extract_coingecko(session: aiohttp.ClientSession, out: Path, coin_ids: list[str], days: int) -> None:
    key = os.getenv("COINGECKO_API_KEY")
    headers = {"x-cg-demo-api-key": key} if key else {}
    if not key:
        logger.warning("COINGECKO_API_KEY não definida: requisições sem chave podem ser recusadas ou ter limite menor")
    for coin_id in coin_ids:
        params = {"vs_currency": "usd", "days": days, "interval": "daily"}
        async with session.get(COINGECKO_URL.format(coin_id=coin_id), params=params, headers=headers) as resp:
            if resp.status != 200:
                logger.error("%s: HTTP %d %s", coin_id, resp.status, await resp.text())
                continue
            payload = await resp.json()
        frames = [
            pd.DataFrame(payload[field], columns=["timestamp", name]).set_index("timestamp")
            for field, name in (("prices", "price"), ("market_caps", "market_cap"), ("total_volumes", "total_volume"))
        ]
        df = pd.concat(frames, axis=1).reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        write_parquet(df, out / "coingecko" / f"coin_id={coin_id}" / "data.parquet")
        logger.info("%s coingecko salvo: %d dias", coin_id, len(df))
        await asyncio.sleep(2.5)  # Demo: ~30 req/min


async def run(args: argparse.Namespace) -> None:
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if args.source == "fng":
            await extract_fng(session, args.output)
        elif args.source == "funding":
            await extract_funding(session, args.output, args.symbols)
        else:
            await extract_coingecko(session, args.output, args.coins, args.days)


def main() -> None:
    p = argparse.ArgumentParser(description="Extrai dados de contexto de mercado cripto.")
    p.add_argument("--output", type=Path, default=Path("data/raw"))
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--log-file", type=Path, default=Path("logs/extract_market_context.log"))
    sub = p.add_subparsers(dest="source", required=True)
    sub.add_parser("fng")
    f = sub.add_parser("funding")
    f.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    c = sub.add_parser("coingecko")
    c.add_argument("--coins", nargs="+", default=["bitcoin", "ethereum"], help="IDs da CoinGecko")
    c.add_argument("--days", type=int, default=365, help="Demo API: máximo 365")
    args = p.parse_args()

    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=args.log_level.upper(), format=LOG_FORMAT, force=True,
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(args.log_file, encoding="utf-8")],
    )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
