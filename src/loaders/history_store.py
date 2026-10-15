"""Histórico diário dos snapshots: data/signals/history/date=YYYY-MM-DD/signals.parquet.

Um arquivo por dia; reexecutar no mesmo dia sobrescreve o snapshot daquele dia.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .parquet_loader import write_parquet

HISTORY_DIR = Path("data/signals/history")
_PREFIX = "date="


def snapshot_path(day: pd.Timestamp, base: Path = HISTORY_DIR) -> Path:
    return base / f"{_PREFIX}{day:%Y-%m-%d}" / "signals.parquet"


def write_snapshot(df: pd.DataFrame, day: pd.Timestamp, base: Path = HISTORY_DIR) -> Path:
    return write_parquet(df, snapshot_path(day, base), compression="zstd")


def read_previous(day: pd.Timestamp, base: Path = HISTORY_DIR) -> pd.DataFrame | None:
    """Snapshot do último dia salvo estritamente antes de `day`, ou None se não houver."""
    if not base.is_dir():
        return None
    current = f"{day:%Y-%m-%d}"
    days = sorted(
        p.name.removeprefix(_PREFIX)
        for p in base.iterdir()
        if p.name.startswith(_PREFIX) and (p / "signals.parquet").is_file()
    )
    earlier = [d for d in days if d < current]
    if not earlier:
        return None
    return pd.read_parquet(base / f"{_PREFIX}{earlier[-1]}" / "signals.parquet")
