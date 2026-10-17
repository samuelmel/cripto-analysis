"""Histórico de estados das posições e avisos enviados (Parquet, append-only) em `data/state/`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..transformers.position_log import (
    NOTIFICATIONS_SCHEMA,
    POSITION_STATE_LOG_SCHEMA,
    empty_notifications,
    empty_state_log,
)
from .parquet_loader import write_parquet
from .state_store import notifications_path, position_states_path


def read_state_log(path: Path | None = None) -> pd.DataFrame:
    p = path or position_states_path()
    return pd.read_parquet(p).astype(POSITION_STATE_LOG_SCHEMA) if p.is_file() else empty_state_log()


def append_state_log(rows: pd.DataFrame, path: Path | None = None) -> int:
    """Acrescenta linhas novas sem tocar nas antigas. Devolve quantas entraram."""
    if rows.empty:
        return 0
    p = path or position_states_path()
    current = read_state_log(p)
    write_parquet(pd.concat([current, rows], ignore_index=True) if not current.empty else rows, p)
    return len(rows)


def read_notifications(path: Path | None = None) -> pd.DataFrame:
    p = path or notifications_path()
    return pd.read_parquet(p).astype(NOTIFICATIONS_SCHEMA) if p.is_file() else empty_notifications()


def append_notifications(rows: pd.DataFrame, path: Path | None = None) -> int:
    if rows.empty:
        return 0
    p = path or notifications_path()
    current = read_notifications(p)
    write_parquet(pd.concat([current, rows], ignore_index=True) if not current.empty else rows, p)
    return len(rows)
