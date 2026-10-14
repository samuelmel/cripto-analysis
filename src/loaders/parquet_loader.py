"""Escrita Parquet atômica (CLAUDE.md §3): o arquivo anterior só é substituído após gravação completa."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

DAILY_SIGNALS_PATH = Path("frontend/public/daily_signals.parquet")

Compression = Literal["snappy", "gzip", "brotli", "lz4", "zstd"]


def write_parquet(df: pd.DataFrame, path: Path, compression: Compression = "snappy") -> Path:
    """Grava `df` em `path` via arquivo temporário + rename. Retorna o caminho final."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        df.to_parquet(tmp, index=False, compression=compression, engine="pyarrow")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def write_daily_signals(df: pd.DataFrame, path: Path = DAILY_SIGNALS_PATH) -> Path:
    """Publica o snapshot do detector para o frontend (snappy: legível no navegador sem codec extra)."""
    return write_parquet(df, path, compression="snappy")
