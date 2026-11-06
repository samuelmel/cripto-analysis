"""Suas posições (compras reais) em data/state/positions.parquet (repositório de estado, ver `state_store`)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .parquet_loader import write_parquet
from .state_store import positions_path

POSITIONS_PATH = positions_path()

POSITIONS_SCHEMA: dict[str, str] = {
    "position_id": "string",
    "symbol": "string",
    "entry_ts": "datetime64[ns, UTC]",
    "entry_price": "float64",
    "qty": "float64",
    "closed": "bool",
    "exit_ts": "datetime64[ns, UTC]",
    "exit_price": "float64",
}


def read_positions(path: Path = POSITIONS_PATH) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in POSITIONS_SCHEMA.items()})
    return pd.read_parquet(path).astype(POSITIONS_SCHEMA)


def write_positions(df: pd.DataFrame, path: Path = POSITIONS_PATH) -> Path:
    return write_parquet(df[list(POSITIONS_SCHEMA)].astype(POSITIONS_SCHEMA), path, compression="zstd")
