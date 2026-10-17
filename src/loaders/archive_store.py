"""Base de pesquisa montada do arquivo oficial da Binance (data.binance.vision), separada da base do pipeline diário.

    data/archive/ohlcv_1d/symbol=LUNA_USDT/data.parquet   candles (mesmo layout e upsert de market_store)
    data/archive/revisions/data.parquet                    valores de candles alterados por releitura
    data/archive/manifest/data.parquet                     cada ZIP ingerido: chave, ETag, SHA-256, linhas (append-only)
    data/archive/catalog/data.parquet                      catálogo de pares da última listagem
    data/archive/catalog/history.parquet                   todas as listagens (com `listed_at`), append-only
    data/archive/sync_log/data.parquet                     resultado de cada par em cada sincronização (append-only)
    data/archive/point_in_time/<nome>.parquet              universo histórico, eventos e resumo de sobrevivência

Separada de propósito: o pipeline diário continua lendo só `data/market` (sua base e seu comportamento não mudam);
a pesquisa point-in-time lê daqui. Nada aqui é versionado no Git (`/data/` está no .gitignore).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..extractors.binance_archive import CATALOG_SCHEMA, MANIFEST_SCHEMA
from .market_store import read_ohlcv, write_ohlcv
from .parquet_loader import write_parquet

ARCHIVE_DIR = Path("data/archive")

SYNC_LOG_SCHEMA: dict[str, str] = {
    "synced_at": "datetime64[ns, UTC]",
    "symbol": "string",
    "status": "string",     # ok / erro
    "files": "int64",       # ZIPs novos ou revisados baixados
    "rows": "int64",        # candles gravados
    "detail": "string",     # mensagem do erro (sem cabeçalhos nem chaves)
}


def _read(path: Path, schema: dict[str, str]) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
    return pd.read_parquet(path).astype(schema)


def _append(new: pd.DataFrame, path: Path, schema: dict[str, str]) -> Path:
    merged = pd.concat([_read(path, schema), new.astype(schema)], ignore_index=True).drop_duplicates(keep="first")
    return write_parquet(merged.astype(schema), path, compression="zstd")


def archive_symbols(base: Path = ARCHIVE_DIR) -> list[str]:
    """Pares com candles na base do arquivo (formato BASE/QUOTE)."""
    root = base / "ohlcv_1d"
    if not root.is_dir():
        return []
    names = [p.name.removeprefix("symbol=") for p in root.iterdir() if (p / "data.parquet").is_file()]
    return sorted(n.replace("_", "/", 1) for n in names)


def read_archive_candles(symbols: list[str] | None = None, base: Path = ARCHIVE_DIR) -> pd.DataFrame:
    return read_ohlcv(symbols if symbols is not None else archive_symbols(base), base)


def write_archive_candles(df: pd.DataFrame, ingested_at: pd.Timestamp, base: Path = ARCHIVE_DIR) -> int:
    return write_ohlcv(df, base, ingested_at=ingested_at)


def read_manifest(base: Path = ARCHIVE_DIR) -> pd.DataFrame:
    return _read(base / "manifest" / "data.parquet", {**MANIFEST_SCHEMA, "fetched_at": "datetime64[ns, UTC]"})


def append_manifest(manifest: pd.DataFrame, fetched_at: pd.Timestamp, base: Path = ARCHIVE_DIR) -> Path:
    schema = {**MANIFEST_SCHEMA, "fetched_at": "datetime64[ns, UTC]"}
    return _append(manifest.assign(fetched_at=fetched_at), base / "manifest" / "data.parquet", schema)


def known_etags(manifest: pd.DataFrame) -> dict[str, str]:
    """Chave do ZIP -> ETag da versão mais recente já ingerida."""
    if manifest.empty:
        return {}
    latest = manifest.sort_values("fetched_at").drop_duplicates("key", keep="last")
    return {str(k): str(e) for k, e in zip(latest["key"], latest["etag"], strict=True)}


def write_catalog(catalog: pd.DataFrame, listed_at: pd.Timestamp, base: Path = ARCHIVE_DIR) -> Path:
    schema = {**CATALOG_SCHEMA, "listed_at": "datetime64[ns, UTC]"}
    snapshot = catalog.assign(listed_at=listed_at).astype(schema)
    _append(snapshot, base / "catalog" / "history.parquet", schema)
    return write_parquet(snapshot, base / "catalog" / "data.parquet", compression="zstd")


def read_catalog(base: Path = ARCHIVE_DIR) -> pd.DataFrame:
    return _read(base / "catalog" / "data.parquet", {**CATALOG_SCHEMA, "listed_at": "datetime64[ns, UTC]"})


def append_sync_log(events: pd.DataFrame, base: Path = ARCHIVE_DIR) -> Path:
    return _append(events, base / "sync_log" / "data.parquet", SYNC_LOG_SCHEMA)


def read_sync_log(base: Path = ARCHIVE_DIR) -> pd.DataFrame:
    return _read(base / "sync_log" / "data.parquet", SYNC_LOG_SCHEMA)


def write_point_in_time(name: str, df: pd.DataFrame, base: Path = ARCHIVE_DIR) -> Path:
    return write_parquet(df, base / "point_in_time" / f"{name}.parquet", compression="zstd")
