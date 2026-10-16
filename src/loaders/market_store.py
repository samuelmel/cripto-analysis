"""Base histórica local em Parquet: candles diários por ativo e Fear & Greed completo.

    data/market/ohlcv_1d/symbol=BTC_USDT/data.parquet
    data/market/fng/data.parquet

Escrita é upsert: o histórico salvo é unido ao novo e (timestamp, symbol) duplicado fica com a
versão mais recente; com `ingested_at`, a versão substituída fica registrada em `revisions/data.parquet`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..transformers.dataset import DATASET_MANIFEST_SCHEMA, REVISION_SCHEMA, candle_revisions
from .parquet_loader import write_parquet

MARKET_DIR = Path("data/market")


def _ohlcv_path(symbol: str, base: Path) -> Path:
    return base / "ohlcv_1d" / f"symbol={symbol.replace('/', '_')}" / "data.parquet"


def _fng_path(base: Path) -> Path:
    return base / "fng" / "data.parquet"


class MixedSourceError(ValueError):
    """Candles de outra fonte para uma moeda que já tem base de uma fonte diferente."""


def _upsert(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    merged = new if old is None or old.empty else pd.concat([old, new], ignore_index=True)
    merged = merged.drop_duplicates(["symbol", "timestamp"], keep="last")
    return merged.sort_values(["symbol", "timestamp"], ignore_index=True)


def read_ohlcv(symbols: list[str], base: Path = MARKET_DIR) -> pd.DataFrame:
    """Candles salvos dos `symbols` (os sem base local são ignorados)."""
    paths = [p for s in symbols if (p := _ohlcv_path(s, base)).is_file()]
    if not paths:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)


def last_timestamp(symbol: str, base: Path = MARKET_DIR) -> pd.Timestamp | None:
    path = _ohlcv_path(symbol, base)
    if not path.is_file():
        return None
    ts = pd.read_parquet(path, columns=["timestamp"])["timestamp"]
    return None if ts.empty else pd.Timestamp(ts.max())


def _revisions_path(base: Path) -> Path:
    return base / "revisions" / "data.parquet"


def read_revisions(base: Path = MARKET_DIR) -> pd.DataFrame:
    """Trilha de candles cuja nova leitura alterou um valor já gravado (REVISION_SCHEMA)."""
    path = _revisions_path(base)
    if not path.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in REVISION_SCHEMA.items()})
    return pd.read_parquet(path).astype(REVISION_SCHEMA)


def write_ohlcv(df: pd.DataFrame, base: Path = MARKET_DIR, *, ingested_at: pd.Timestamp | None = None) -> int:
    """Upsert por ativo. Retorna o número de ativos gravados.

    Com `ingested_at` (injetado pelo entrypoint), todo valor já gravado que a nova leitura altera vira um evento em
    `revisions/` (o valor antigo nunca some sem registro). Reexecutar com os mesmos candles não muda nada.
    """
    revisions: list[pd.DataFrame] = []
    for symbol, part in df.groupby("symbol", observed=True):
        path = _ohlcv_path(str(symbol), base)
        old = pd.read_parquet(path) if path.is_file() else None
        if old is not None and "source" in old.columns:
            stored, incoming = set(old["source"].dropna().unique()), set(part["source"].dropna().unique())
            if stored and incoming and stored != incoming:
                raise MixedSourceError(
                    f"{symbol}: a base tem candles de {sorted(stored)} e chegaram de {sorted(incoming)}; "
                    "não misturamos fornecedores (apague a base dessa moeda para trocar de fonte)"
                )
        if ingested_at is not None:
            revisions.append(candle_revisions(old, part, ingested_at))
        write_parquet(_upsert(old, part), path, compression="zstd")
    changed = [r for r in revisions if not r.empty]
    if changed:
        trail = pd.concat([read_revisions(base), *changed], ignore_index=True)
        write_parquet(trail.astype(REVISION_SCHEMA), _revisions_path(base), compression="zstd")
    return int(df["symbol"].nunique())


def _dataset_manifest_path(base: Path) -> Path:
    return base / "dataset_manifest" / "history.parquet"


def read_dataset_manifests(base: Path = MARKET_DIR) -> pd.DataFrame:
    """Fingerprint por moeda dos candles usados em cada execução (append-only, com `run_ts`)."""
    path = _dataset_manifest_path(base)
    schema = {"run_ts": "datetime64[ns, UTC]", **DATASET_MANIFEST_SCHEMA}
    if not path.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
    return pd.read_parquet(path).astype(schema)


def append_dataset_manifest(manifest: pd.DataFrame, run_ts: pd.Timestamp, base: Path = MARKET_DIR) -> Path:
    """Registra quais dados (linhas, intervalo e SHA-256 por moeda) a execução `run_ts` usou."""
    schema = {"run_ts": "datetime64[ns, UTC]", **DATASET_MANIFEST_SCHEMA}
    new = manifest.assign(run_ts=run_ts)[list(schema)].astype(schema)
    merged = pd.concat([read_dataset_manifests(base), new], ignore_index=True)
    return write_parquet(merged.astype(schema), _dataset_manifest_path(base), compression="zstd")


def _read(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.is_file() else pd.DataFrame()


def _write(df: pd.DataFrame, path: Path) -> None:
    old = pd.read_parquet(path) if path.is_file() else None
    write_parquet(_upsert(old, df), path, compression="zstd")


def read_fng(base: Path = MARKET_DIR) -> pd.DataFrame:
    return _read(_fng_path(base))


def write_fng(df: pd.DataFrame, base: Path = MARKET_DIR) -> None:
    _write(df, _fng_path(base))


def read_coingecko(base: Path = MARKET_DIR) -> pd.DataFrame:
    """Snapshots diários de market cap acumulados (um por execução)."""
    return _read(base / "coingecko" / "data.parquet")


def write_coingecko(df: pd.DataFrame, base: Path = MARKET_DIR) -> None:
    _write(df, base / "coingecko" / "data.parquet")
