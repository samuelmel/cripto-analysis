"""Baixa da Bitstamp (API pública oficial) os candles diários em USD desde 2011, para estender o histórico do BTC.

Entrypoint (CLAUDE.md §1): rede e disco. Grava em `data/archive_bitstamp/ohlcv_1d/` (mesmo layout das outras bases,
upsert idempotente com trilha de revisões). Roda no GitHub Actions (workflow "Base de pesquisa"): a Bitstamp não é
acessível do ambiente de desenvolvimento.

    uv run python research/build_bitstamp.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extractors import ExtractorError  # noqa: E402
from src.extractors.bitstamp_adapter import BitstampAdapter  # noqa: E402
from src.loaders.market_store import write_ohlcv  # noqa: E402

BITSTAMP_DIR = Path("data/archive_bitstamp")
PAIRS = ("BTC/USD", "ETH/USD", "LTC/USD", "XRP/USD")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    now = datetime.now(timezone.utc)
    failed = []
    for pair in PAIRS:
        try:
            candles = BitstampAdapter([pair]).extract(None, now)
        except ExtractorError as exc:
            logging.error("%s: falhou: %s", pair, exc)
            failed.append(pair)
            continue
        if candles.empty:
            logging.warning("%s: nenhum candle", pair)
            continue
        write_ohlcv(candles, BITSTAMP_DIR, ingested_at=pd.Timestamp(now))
        logging.info("%s: %d candles, %s a %s", pair, len(candles), f"{candles['timestamp'].min():%Y-%m-%d}",
                     f"{candles['timestamp'].max():%Y-%m-%d}")
    print(f"Bitstamp: {len(PAIRS) - len(failed)} de {len(PAIRS)} pares gravados em {BITSTAMP_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
