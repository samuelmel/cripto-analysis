"""Escrita Parquet atômica compartilhada pelos extratores de fontes adicionais."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_parquet(df: pd.DataFrame, path: Path, compression: str = "zstd") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False, compression=compression, engine="pyarrow")
    tmp.replace(path)


def write_by_month(df: pd.DataFrame, base: Path, ts_col: str = "timestamp") -> int:
    """Grava um arquivo por partição year=YYYY/month=MM. Retorna número de partições escritas."""
    if df.empty:
        return 0
    keys = df[ts_col].dt.year * 100 + df[ts_col].dt.month
    for key, part in df.groupby(keys):
        year, month = divmod(int(key), 100)
        write_parquet(part, base / f"year={year}" / f"month={month:02d}" / "data.parquet")
    return int(keys.nunique())
