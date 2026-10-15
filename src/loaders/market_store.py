"""Base histórica local em Parquet: candles diários por ativo e Fear & Greed completo.

    data/market/ohlcv_1d/symbol=BTC_USDT/data.parquet
    data/market/fng/data.parquet

Escrita é upsert: o histórico salvo é unido ao novo e (timestamp, symbol) duplicado fica com a
versão mais recente.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

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


def write_ohlcv(df: pd.DataFrame, base: Path = MARKET_DIR) -> int:
    """Upsert por ativo. Retorna o número de ativos gravados."""
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
        write_parquet(_upsert(old, part), path, compression="zstd")
    return int(df["symbol"].nunique())


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
