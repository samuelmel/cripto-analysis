"""Extração histórica de OHLCV via CCXT (assíncrono) com persistência em Parquet particionado.

Layout (Hive):
    data/raw/ohlcv/exchange=<ex>/timeframe=<tf>/symbol=<BASE_QUOTE>/year=YYYY/month=MM/part-<first_ts>-<last_ts>.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt.async_support as ccxt
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("ms", tz="UTC")),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
    ]
)
PART_RE = re.compile(r"part-(\d+)-(\d+)\.parquet$")

logger = logging.getLogger("extract_historical")


@dataclass(frozen=True)
class Config:
    exchange: str
    symbols: list[str]
    timeframe: str
    years: int
    output: Path
    concurrency: int
    limit: int
    max_retries: int
    compression: str


def setup_logging(level: str, log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT, handlers=handlers, force=True)


def symbol_dir(cfg: Config, symbol: str) -> Path:
    return (
        cfg.output
        / f"exchange={cfg.exchange}"
        / f"timeframe={cfg.timeframe}"
        / f"symbol={symbol.replace('/', '_')}"
    )


def last_saved_ts(base: Path) -> int | None:
    """Maior timestamp persistido, lido do nome dos arquivos (sem abrir Parquet)."""
    if not base.exists():
        return None
    ends = [int(m.group(2)) for p in base.rglob("part-*.parquet") if (m := PART_RE.search(p.name))]
    return max(ends) if ends else None


def write_month(cfg: Config, symbol: str, rows: list[list]) -> int:
    df = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates("timestamp").sort_values("timestamp")
    first, last = int(df["timestamp"].iloc[0]), int(df["timestamp"].iloc[-1])
    dt = datetime.fromtimestamp(first / 1000, tz=timezone.utc)
    target = symbol_dir(cfg, symbol) / f"year={dt.year}" / f"month={dt.month:02d}"
    target.mkdir(parents=True, exist_ok=True)

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    final = target / f"part-{first}-{last}.parquet"
    tmp = final.with_suffix(".tmp")
    pq.write_table(table, tmp, compression=cfg.compression)
    tmp.replace(final)  # escrita atômica: arquivo parcial nunca vira partição válida
    return len(df)


def month_key(ts_ms: int) -> tuple[int, int]:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.year, dt.month


async def fetch_page(
    exchange: ccxt.Exchange, cfg: Config, symbol: str, since: int
) -> list[list]:
    for attempt in range(1, cfg.max_retries + 1):
        try:
            return await exchange.fetch_ohlcv(symbol, cfg.timeframe, since=since, limit=cfg.limit)
        except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as exc:
            wait = min(60, 2**attempt)
            logger.warning("%s rate limit (tentativa %d): %s | aguardando %ss", symbol, attempt, exc, wait)
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            wait = min(30, 2**attempt)
            logger.warning("%s erro de rede (tentativa %d): %s | aguardando %ss", symbol, attempt, exc, wait)
        await asyncio.sleep(wait)
    raise RuntimeError(f"{symbol}: falha após {cfg.max_retries} tentativas em since={since}")


async def extract_symbol(
    exchange: ccxt.Exchange, cfg: Config, symbol: str, sem: asyncio.Semaphore
) -> None:
    async with sem:
        tf_ms = exchange.parse_timeframe(cfg.timeframe) * 1000
        now = exchange.milliseconds()
        default_start = int((datetime.now(timezone.utc) - timedelta(days=365 * cfg.years)).timestamp() * 1000)
        resume = last_saved_ts(symbol_dir(cfg, symbol))
        since = resume + tf_ms if resume is not None else default_start
        logger.info("%s iniciando em %s", symbol, datetime.fromtimestamp(since / 1000, tz=timezone.utc).isoformat())

        buffer: list[list] = []
        current_month: tuple[int, int] | None = None
        total = 0

        while since < now - tf_ms:
            page = await fetch_page(exchange, cfg, symbol, since)
            if not page:
                if resume is None and not buffer and since < now:
                    # Par ainda não listado nessa data: salta para frente até encontrar dados.
                    since += tf_ms * cfg.limit
                    continue
                break

            for candle in page:
                key = month_key(candle[0])
                if current_month is not None and key != current_month and buffer:
                    total += write_month(cfg, symbol, buffer)
                    logger.info("%s %04d-%02d salvo (%d linhas acumuladas)", symbol, *current_month, total)
                    buffer = []
                current_month = key
                buffer.append(candle)

            next_since = page[-1][0] + tf_ms
            if next_since <= since:
                break
            since = next_since

        # Exclui o candle ainda aberto para não persistir dados incompletos.
        buffer = [c for c in buffer if c[0] + tf_ms <= now]
        if buffer:
            total += write_month(cfg, symbol, buffer)
        logger.info("%s concluído: %d linhas novas", symbol, total)


async def run(cfg: Config) -> int:
    exchange_cls = getattr(ccxt, cfg.exchange)
    exchange: ccxt.Exchange = exchange_cls({"enableRateLimit": True, "timeout": 30000})
    failures = 0
    try:
        await exchange.load_markets()
        if not exchange.has.get("fetchOHLCV"):
            raise SystemExit(f"{cfg.exchange} não suporta fetchOHLCV")
        if cfg.timeframe not in exchange.timeframes:
            raise SystemExit(f"timeframe '{cfg.timeframe}' indisponível em {cfg.exchange}")

        valid = [s for s in cfg.symbols if s in exchange.markets]
        for s in set(cfg.symbols) - set(valid):
            logger.error("símbolo ignorado (não listado): %s", s)

        sem = asyncio.Semaphore(cfg.concurrency)
        results = await asyncio.gather(
            *(extract_symbol(exchange, cfg, s, sem) for s in valid), return_exceptions=True
        )
        for symbol, result in zip(valid, results):
            if isinstance(result, Exception):
                failures += 1
                logger.error("%s falhou: %s", symbol, result, exc_info=result)
    finally:
        await exchange.close()
    return failures


def parse_args() -> tuple[Config, str, Path | None]:
    p = argparse.ArgumentParser(description="Extrai OHLCV histórico para Parquet particionado.")
    p.add_argument("--exchange", default="binance")
    p.add_argument("--symbols", nargs="+", default=["BTC/USDT", "ETH/USDT"])
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--output", type=Path, default=Path("data/raw/ohlcv"))
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--max-retries", type=int, default=6)
    p.add_argument("--compression", default="zstd", choices=["zstd", "snappy", "gzip", "none"])
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--log-file", type=Path, default=Path("logs/extract_historical.log"))
    a = p.parse_args()
    cfg = Config(
        exchange=a.exchange,
        symbols=a.symbols,
        timeframe=a.timeframe,
        years=a.years,
        output=a.output,
        concurrency=a.concurrency,
        limit=a.limit,
        max_retries=a.max_retries,
        compression=a.compression,
    )
    return cfg, a.log_level, a.log_file


def main() -> None:
    cfg, level, log_file = parse_args()
    setup_logging(level, log_file)
    failures = asyncio.run(run(cfg))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
