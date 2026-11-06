"""Previsões dos modelos em sombra e histórico do Fear & Greed na pasta de estado (repositório de estado), append-only.

Regras puras (cadeia de hash, revisões do F&G): `transformers/model_shadow.py`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..transformers.model_shadow import (
    FNG_HISTORY_SCHEMA,
    PREDICTION_LOG_SCHEMA,
    chain_rows,
    empty_log,
    new_fng_rows,
    verify_chain,
)
from .parquet_loader import write_parquet
from .state_store import fng_history_path, model_predictions_path


class PredictionLogIntegrityError(RuntimeError):
    """A cadeia de hash das previsões não confere: o passado foi alterado."""


def read_predictions(path: Path | None = None) -> pd.DataFrame:
    p = path or model_predictions_path()
    if not p.is_file():
        return empty_log()
    return pd.read_parquet(p).astype(PREDICTION_LOG_SCHEMA)


def append_predictions(rows: pd.DataFrame, path: Path | None = None) -> int:
    """Acrescenta as previsões novas; confere a cadeia antes e não grava nada se estiver quebrada."""
    p = path or model_predictions_path()
    current = read_predictions(p)
    problems = verify_chain(current)
    if problems:
        raise PredictionLogIntegrityError("registro de previsões adulterado, nada foi gravado: " + "; ".join(problems[:3]))
    fresh = chain_rows(current, rows)
    if fresh.empty:
        return 0
    write_parquet(pd.concat([current, fresh], ignore_index=True) if not current.empty else fresh, p)
    return len(fresh)


def read_fng_history(path: Path | None = None) -> pd.DataFrame:
    p = path or fng_history_path()
    if not p.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in FNG_HISTORY_SCHEMA.items()})
    return pd.read_parquet(p).astype(FNG_HISTORY_SCHEMA)


def append_fng_history(fng: pd.DataFrame, seen_at: pd.Timestamp, path: Path | None = None) -> int:
    """Guarda as leituras (dia, valor) ainda não vistas; devolve quantas entraram."""
    p = path or fng_history_path()
    current = read_fng_history(p)
    fresh = new_fng_rows(current, fng, seen_at)
    if fresh.empty:
        return 0
    write_parquet(pd.concat([current, fresh], ignore_index=True) if not current.empty else fresh, p)
    return len(fresh)
