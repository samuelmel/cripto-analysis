"""Baixa do arquivo oficial da Binance os pares cotados em BTC que ampliam o histórico das moedas em USDT.

Entrypoint (CLAUDE.md §1): rede e disco. Seleciona, no catálogo de pares `*BTC`, os que começaram ANTES do par em USDT
da mesma moeda (ou que nunca tiveram par em USDT), sem bases excluídas e sem tokens alavancados, e grava em
`data/archive_btc/` (mesmo layout de `data/archive`, base separada). A conversão para dólar e a emenda com os
candles em USDT são puras: `src/transformers/quote_conversion.py`.

    uv run python research/build_btc_pairs.py

Incremental e idempotente (ETag): reexecutar não baixa de novo nem duplica. Um par que falha vai para o log e o
script termina com código 1, sem tocar nos outros.
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extractors import ExtractorError  # noqa: E402
from src.extractors.binance_archive import ArchiveKey, BinanceArchiveAdapter, archive_symbol, catalog_frame  # noqa: E402
from src.loaders.archive_store import (  # noqa: E402
    SYNC_LOG_SCHEMA,
    append_manifest,
    append_sync_log,
    known_etags,
    read_catalog,
    read_manifest,
    write_archive_candles,
    write_catalog,
)
from src.transformers.point_in_time import PointInTimeRules  # noqa: E402

BTC_DIR = Path("data/archive_btc")
QUOTE = "BTC"
logger = logging.getLogger("btc_pairs")


def extending_pairs(btc: pd.DataFrame, usdt: pd.DataFrame, rules: PointInTimeRules) -> list[str]:
    """Pares BASE/BTC que começam antes do BASE/USDT (ou sem BASE/USDT), fora das exclusões e dos alavancados."""
    first_usdt = dict(zip(usdt["symbol"].astype(str).str.split("/").str[0], usdt["first_month"].astype(str), strict=True))
    bases = set(btc["symbol"].astype(str).str.split("/").str[0]) | set(first_usdt)
    out = []
    for sym, first in zip(btc["symbol"].astype(str), btc["first_month"].astype(str), strict=True):
        base = sym.split("/")[0]
        leveraged = any(base.endswith(x) and base[: -len(x)] in bases for x in rules.leveraged_suffixes)
        if base in rules.excluded or leveraged or base == "BTC":
            continue
        if base not in first_usdt or first < first_usdt[base]:
            out.append(sym)
    return sorted(out)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    now = datetime.now(timezone.utc)
    stamp = pd.Timestamp(now)
    names = BinanceArchiveAdapter.list_symbols(QUOTE)
    with ThreadPoolExecutor(max_workers=8) as pool:
        listings: dict[str, list[ArchiveKey]] = dict(zip(names, pool.map(BinanceArchiveAdapter.list_keys, names), strict=True))
    catalog = catalog_frame(listings, QUOTE)
    write_catalog(catalog, stamp, BTC_DIR)
    usdt = read_catalog()
    if usdt.empty:
        print("catálogo USDT ausente: rode `python -m src.archive catalog` antes", file=sys.stderr)
        return 1
    targets = extending_pairs(catalog, usdt, PointInTimeRules())
    logger.info("%d pares em BTC no arquivo; %d ampliam o histórico", len(catalog), len(targets))
    known = known_etags(read_manifest(BTC_DIR))

    def fetch(symbol: str) -> tuple[str, pd.DataFrame, pd.DataFrame, str | None]:
        try:
            adapter = BinanceArchiveAdapter([symbol], quote=QUOTE, known=known, workers=8,
                                            listings={archive_symbol(symbol): listings.get(archive_symbol(symbol), [])})
            candles, manifest = adapter.extract_with_manifest(None, now)
            return symbol, candles, manifest, None
        except ExtractorError as exc:
            return symbol, pd.DataFrame(), pd.DataFrame(), str(exc)

    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, future in enumerate(as_completed([pool.submit(fetch, s) for s in targets]), start=1):
            symbol, candles, manifest, error = future.result()
            if error is None:
                if not candles.empty:
                    write_archive_candles(candles, stamp, BTC_DIR)
                if not manifest.empty:
                    append_manifest(manifest, stamp, BTC_DIR)
            else:
                failed.append(symbol)
                logger.error("%s: falhou: %s", symbol, error)
            event = {"synced_at": stamp, "symbol": symbol, "status": "ok" if error is None else "erro",
                     "files": len(manifest), "rows": len(candles), "detail": (error or "")[:300]}
            append_sync_log(pd.DataFrame([event])[list(SYNC_LOG_SCHEMA)], BTC_DIR)
            if i % 25 == 0 or i == len(targets):
                logger.info("%d/%d pares", i, len(targets))
    print(f"pares BTC: {len(targets)} processados, {len(failed)} com falha (data/archive_btc/sync_log)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
