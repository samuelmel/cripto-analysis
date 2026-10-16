"""Base de pesquisa point-in-time a partir do arquivo oficial da Binance (data.binance.vision).

Uso (da raiz do projeto):
    uv run python -m src.archive catalog                  lista todos os pares USDT do arquivo (vivos e deslistados)
    uv run python -m src.archive sync --symbols BTC/USDT LUNA/USDT
    uv run python -m src.archive sync --all               todos os pares USDT do catálogo, exceto alavancados e
                                                          bases excluídas (stablecoins, fiat, ouro, embrulhados)
    uv run python -m src.archive universe                 universo histórico, eventos e resumo de sobrevivência
    uv run python -m src.archive status                   o que há na base e o fingerprint dos dados

Entrypoint (CLAUDE.md §1): só orquestra rede, disco e relógio; as regras estão em `transformers/point_in_time.py`,
`transformers/dataset.py` e `transformers/data_quality.py`. Incremental e idempotente: o que já foi ingerido com o
mesmo ETag não é baixado de novo, e reexecutar não duplica candles. Uma falha num par é registrada no sync_log e
não toca nos dados já gravados dos outros pares (escrita atômica por arquivo).

Não afeta o pipeline diário: grava em data/archive, não em data/market nem em frontend/public.
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from .config import UNIVERSE
from .extractors import ExtractorError
from .extractors.binance_archive import ArchiveKey, BinanceArchiveAdapter, archive_symbol, catalog_frame, pair_symbol
from .loaders.archive_store import (
    SYNC_LOG_SCHEMA,
    append_manifest,
    append_sync_log,
    archive_symbols,
    known_etags,
    read_archive_candles,
    read_catalog,
    read_manifest,
    write_archive_candles,
    write_catalog,
    write_point_in_time,
)
from .loaders.market_store import MixedSourceError
from .transformers.data_quality import audit_candles
from .transformers.dataset import candle_fingerprint, dataset_manifest
from .transformers.point_in_time import (
    EVENT_GAP,
    EVENT_LAST,
    PointInTimeRules,
    listing_events,
    review_flags,
    survivorship_summary,
    universe_history,
)

logger = logging.getLogger("archive")
QUOTE = "USDT"
LISTING_WORKERS = 8


def _list_all(names: list[str]) -> dict[str, list[ArchiveKey]]:
    with ThreadPoolExecutor(max_workers=LISTING_WORKERS) as pool:
        return dict(zip(names, pool.map(BinanceArchiveAdapter.list_keys, names), strict=True))


def _candidates(catalog: pd.DataFrame, rules: PointInTimeRules) -> list[str]:
    """Pares do catálogo que podem entrar no universo: sem base excluída e sem token alavancado."""
    symbols = catalog["symbol"].astype(str).tolist()
    bases = {s.split("/")[0] for s in symbols}

    def keep(s: str) -> bool:
        b = s.split("/")[0]
        lev = any(b.endswith(x) and b[: -len(x)] in bases for x in rules.leveraged_suffixes)
        return b not in rules.excluded and not lev

    return [s for s in symbols if keep(s)]


def cmd_catalog(now: datetime) -> int:
    names = BinanceArchiveAdapter.list_symbols(QUOTE)
    logger.info("arquivo Binance: %d pares em %s; listando os arquivos de cada um", len(names), QUOTE)
    catalog = catalog_frame(_list_all(names), QUOTE)
    write_catalog(catalog, pd.Timestamp(now))
    print(f"catálogo: {len(catalog)} pares em {QUOTE} (vivos e deslistados) gravado em data/archive/catalog")
    return 0


Fetched = tuple[str, pd.DataFrame, pd.DataFrame, str | None]  # (par, candles, manifesto, erro)


def _fetch_one(symbol: str, keys: list[ArchiveKey], known: dict[str, str], now: datetime, workers: int) -> Fetched:
    """Só rede e parse (roda em thread): nada é gravado aqui."""
    try:
        adapter = BinanceArchiveAdapter([symbol], known=known, workers=workers, listings={archive_symbol(symbol): keys})
        candles, manifest = adapter.extract_with_manifest(None, now)
        return symbol, candles, manifest, None
    except ExtractorError as exc:
        return symbol, pd.DataFrame(), pd.DataFrame(), str(exc)


def _store_one(fetched: Fetched, now: datetime) -> dict[str, object]:
    """Grava um par já baixado e verificado (sempre na thread principal: as gravações nunca concorrem)."""
    symbol, candles, manifest, error = fetched
    stamp = pd.Timestamp(now)
    if error is None:
        try:
            if not candles.empty:
                write_archive_candles(candles, stamp)
            if not manifest.empty:
                append_manifest(manifest, stamp)  # depois dos candles: interrompido no meio, o par é baixado de novo
            return {"synced_at": stamp, "symbol": symbol, "status": "ok", "files": len(manifest), "rows": len(candles), "detail": ""}
        except MixedSourceError as exc:
            error = str(exc)
    logger.error("%s: sincronização falhou: %s", symbol, error)
    return {"synced_at": stamp, "symbol": symbol, "status": "erro", "files": 0, "rows": 0, "detail": str(error)[:300]}


def cmd_sync(symbols: list[str] | None, use_all: bool, workers: int, now: datetime, pairs: int = 1) -> int:
    """`workers`: downloads simultâneos por par; `pairs`: pares baixados ao mesmo tempo."""
    rules = PointInTimeRules()
    if use_all:
        names = BinanceArchiveAdapter.list_symbols(QUOTE)
        listings = _list_all(names)
        catalog = catalog_frame(listings, QUOTE)
        write_catalog(catalog, pd.Timestamp(now))
        targets = _candidates(catalog, rules)
    else:
        targets = list(symbols or [])
        listings = _list_all([archive_symbol(s) for s in targets])
    known = known_etags(read_manifest())
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, pairs)) as pool:
        futures = [pool.submit(_fetch_one, s, listings.get(archive_symbol(s), []), known, now, workers) for s in targets]
        for i, future in enumerate(as_completed(futures), start=1):
            event = _store_one(future.result(), now)
            # Log gravado a cada par, logo depois dos dados: uma interrupção não deixa par gravado sem registro.
            append_sync_log(pd.DataFrame([event])[list(SYNC_LOG_SCHEMA)])
            if event["status"] != "ok":
                failed.append(str(event["symbol"]))
            if i % 25 == 0 or i == len(targets):
                logger.info("%d/%d pares sincronizados", i, len(targets))
    print(f"sincronização: {len(targets)} pares processados, {len(failed)} com falha (detalhes em data/archive/sync_log)")
    if failed:
        print("falharam: " + ", ".join(sorted(failed)), file=sys.stderr)
        return 1  # falha parcial não passa em silêncio; os pares que deram certo ficam gravados
    return 0


def cmd_universe(now: datetime) -> int:
    candles = read_archive_candles()
    if candles.empty:
        print("base do arquivo vazia: rode `python -m src.archive sync` antes", file=sys.stderr)
        return 1
    rules = PointInTimeRules()
    history = universe_history(candles, rules)
    events = listing_events(candles, pd.Timestamp(now), rules)
    ended = set(events.loc[events["event"].isin([EVENT_LAST, EVENT_GAP]), "symbol"].astype(str))
    summary = survivorship_summary(history, list(UNIVERSE), ended)
    write_point_in_time("universe_history", history)
    write_point_in_time("listing_events", events)
    write_point_in_time("survivorship", summary)
    catalog = read_catalog()
    flags = review_flags(catalog, rules) if not catalog.empty else pd.DataFrame(columns=["symbol", "flag", "detail"])
    write_point_in_time("review_flags", flags)
    print(f"universo point-in-time: {history['symbol'].nunique()} pares, {history['timestamp'].nunique()} dias")
    if not flags.empty:
        print(f"{len(flags)} par(es) para revisar (não excluídos): {', '.join(flags['symbol'].astype(str).head(10))}"
              + (" ..." if len(flags) > 10 else ""))
    print("por ano: elegíveis por dia (média), distintos, quantos estão na lista de HOJE, quantos pararam depois")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.1f}"))
    return 0


def cmd_status(now: datetime) -> int:
    symbols = archive_symbols()
    candles = read_archive_candles(symbols)
    if candles.empty:
        print("base do arquivo vazia")
        return 0
    manifest = dataset_manifest(candles)
    issues = audit_candles(candles, as_of=pd.Timestamp(now))
    catalog = read_catalog()
    print(f"base do arquivo: {len(symbols)} pares, {len(candles)} candles, "
          f"{candles['timestamp'].min():%Y-%m-%d} a {candles['timestamp'].max():%Y-%m-%d}")
    print(f"fingerprint do conjunto: {candle_fingerprint(candles)}")
    print(f"catálogo: {len(catalog)} pares listados"
          + (f" em {pd.Timestamp(catalog['listed_at'].iloc[0]):%Y-%m-%d %H:%M} UTC" if not catalog.empty else ""))
    print(f"arquivos ingeridos (manifesto): {len(read_manifest())}")
    print(f"pares com candles: {len(manifest)}; problemas de qualidade: {len(issues)} (tipo: contagem)")
    if not issues.empty:
        print(issues.groupby("kind")["count"].sum().to_string())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Base point-in-time do arquivo oficial da Binance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog", help="lista todos os pares USDT do arquivo")
    sync = sub.add_parser("sync", help="baixa (incremental) os candles diários verificados")
    group = sync.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbols", nargs="+", help="pares no formato BASE/USDT")
    group.add_argument("--all", action="store_true", help="todos os candidatos do catálogo")
    group.add_argument("--core", action="store_true", help="as moedas de config.UNIVERSE (lista atual)")
    sync.add_argument("--workers", type=int, default=8, help="downloads simultâneos por par")
    sync.add_argument("--pairs", type=int, default=4, help="pares baixados ao mesmo tempo")
    sub.add_parser("universe", help="universo histórico, eventos e resumo de sobrevivência")
    sub.add_parser("status", help="resumo da base e fingerprint")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    now = datetime.now(timezone.utc)
    try:
        if args.command == "catalog":
            return cmd_catalog(now)
        if args.command == "sync":
            symbols = list(UNIVERSE) if args.core else args.symbols
            for s in symbols or []:
                pair_symbol(archive_symbol(s), QUOTE)  # valida o formato antes de qualquer rede
            return cmd_sync(symbols, args.all, args.workers, now, args.pairs)
        if args.command == "universe":
            return cmd_universe(now)
        return cmd_status(now)
    except ExtractorError as exc:
        logger.error("falhou: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
