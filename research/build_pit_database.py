"""Baixa o histórico diário de TODOS os pares `*USDT` que já existiram na Binance (inclusive deslistados).

Entrypoint (CLAUDE.md §1): faz a coleta e a gravação; nenhuma regra de negócio. Alimenta o universo point-in-time
(`src/transformers/universe_pit.py`) e o estudo de validação do COMPRAR. Grava em `data/market/pit/ohlcv_1d/`, base
separada da usada pelo pipeline diário (que segue só com `config.UNIVERSE`).

Uso:   uv run python research/build_pit_database.py [--refresh] [--limit N]
Fonte: listagem do bucket público data.binance.vision + klines de data-api.binance.vision (mesmo host público já
usado pelo pipeline). Para o par que falhar, o script PARA e mostra o erro com traceback (nada é pulado em silêncio).
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extractors import BinanceAdapter  # noqa: E402
from src.extractors.binance_listing import fetch_usdt_symbols  # noqa: E402
from src.loaders.market_store import last_timestamp, write_ohlcv  # noqa: E402
from src.transformers.universe_pit import candidate_symbols  # noqa: E402

PIT_DIR = Path("data/market/pit")
HOST = "https://data-api.binance.vision"
START = datetime(2017, 7, 1, tzinfo=timezone.utc)

logger = logging.getLogger("build_pit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="baixa de novo mesmo os pares já gravados")
    parser.add_argument("--limit", type=int, default=0, help="só os N primeiros pares (teste)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    symbols = candidate_symbols(fetch_usdt_symbols())
    if args.limit:
        symbols = symbols[: args.limit]
    logger.info("%d pares candidatos (stablecoins, fiduciárias e alavancadas já fora)", len(symbols))
    done = empty = 0
    for i, symbol in enumerate(symbols, start=1):
        if not args.refresh and last_timestamp(symbol, PIT_DIR) is not None:
            continue
        try:
            candles = BinanceAdapter([symbol], host=HOST).extract(START, now + timedelta(days=0))
        except Exception:
            print(f"FALHA em {symbol} ({i}/{len(symbols)}):\n{traceback.format_exc()}")
            return 1
        if candles.empty:
            empty += 1
            logger.warning("%s: sem candles", symbol)
            continue
        write_ohlcv(candles, PIT_DIR)
        done += 1
        if done % 25 == 0:
            logger.info("%d/%d: %s (%d candles)", i, len(symbols), symbol, len(candles))
    logger.info("concluído: %d pares gravados, %d sem dados", done, empty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
