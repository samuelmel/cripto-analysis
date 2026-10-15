"""Escrita Parquet atômica (CLAUDE.md §3): o arquivo anterior só é substituído após gravação completa."""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Literal

import pandas as pd

logger = logging.getLogger(__name__)

DAILY_SIGNALS_PATH = Path("frontend/public/daily_signals.parquet")

Compression = Literal["snappy", "gzip", "brotli", "lz4", "zstd"]

# No Windows, substituir um arquivo que outro processo está lendo (ex.: o dev server servindo o
# Parquet ao navegador) falha com PermissionError por alguns milissegundos: tenta de novo.
REPLACE_ATTEMPTS = 25
REPLACE_WAIT_S = 0.2


def write_parquet(df: pd.DataFrame, path: Path, compression: Compression = "snappy") -> Path:
    """Grava `df` em `path` via arquivo temporário único + rename. Retorna o caminho final.

    Se outro processo mantiver o arquivo aberto sem permitir exclusão (no Windows, um dev server
    com uma leitura pendurada), o rename nunca passa; aí o conteúdo é copiado por cima do arquivo
    existente, que o Windows permite. Perde a atomicidade só nesse caso, e o frontend valida o
    Parquet ao ler.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        df.to_parquet(tmp, index=False, compression=compression, engine="pyarrow")
        for attempt in range(1, REPLACE_ATTEMPTS + 1):
            try:
                tmp.replace(path)
                break
            except PermissionError:
                if attempt < REPLACE_ATTEMPTS:
                    time.sleep(REPLACE_WAIT_S)
                    continue
                logger.warning("%s está aberto por outro processo; gravando por cima (sem rename)", path)
                with tmp.open("rb") as src, path.open("r+b") as dst:
                    shutil.copyfileobj(src, dst)
                    dst.truncate()
    finally:
        tmp.unlink(missing_ok=True)
    return path


def write_daily_signals(df: pd.DataFrame, path: Path = DAILY_SIGNALS_PATH) -> Path:
    """Publica o snapshot do detector para o frontend (snappy: legível no navegador sem codec extra)."""
    return write_parquet(df, path, compression="snappy")
