"""Leitura de Parquet e conversão para JSON. A API não escreve dados."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pandas as pd

from .cache import CACHE


class MissingArtifactError(FileNotFoundError):
    """Artefato opcional ainda não publicado."""


def frame(path: Path, columns: tuple[str, ...] | None = None) -> pd.DataFrame:
    if not path.is_file():
        raise MissingArtifactError(path.name)
    return CACHE.frame(path, columns)


def optional_frame(path: Path, columns: tuple[str, ...] | None = None) -> pd.DataFrame | None:
    return None if not path.is_file() else frame(path, columns)


def records(path: Path, columns: tuple[str, ...] | None = None) -> list[dict[str, object]]:
    return to_records(frame(path, columns))


def optional_records(path: Path, columns: tuple[str, ...] | None = None) -> list[dict[str, object]]:
    f = optional_frame(path, columns)
    return [] if f is None else to_records(f)


def to_records(data: pd.DataFrame) -> list[dict[str, object]]:
    """Datas ISO, NaN/NaT como null e escalares nativos do JSON."""
    raw = data.to_json(orient="records", date_format="iso", date_unit="ms")
    return cast(list[dict[str, object]], json.loads(raw))


def iso_day(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def latest_date(data: pd.DataFrame, column: str) -> str | None:
    if data.empty or column not in data:
        return None
    value = data[column].dropna().max()
    return iso_day(value) if value is not None else None
