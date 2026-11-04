"""Cache de leitura por mtime. O Parquet é a fonte da verdade; nada é mantido após o arquivo mudar."""

from __future__ import annotations

import threading
from pathlib import Path

import pandas as pd

Frame = pd.DataFrame
_Store = dict[tuple[Path, tuple[str, ...] | None], tuple[int, Frame]]


class ParquetCache:
    """Uma instância por processo. A chave inclui as colunas pedidas."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: _Store = {}

    def frame(self, path: Path, columns: tuple[str, ...] | None = None) -> Frame:
        stamp = path.stat().st_mtime_ns
        key = (path, columns)
        with self._lock:
            hit = self._store.get(key)
            if hit is not None and hit[0] == stamp:
                return hit[1]
        frame = pd.read_parquet(path, columns=list(columns) if columns else None)
        with self._lock:
            self._store[key] = (stamp, frame)
        return frame

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


CACHE = ParquetCache()
