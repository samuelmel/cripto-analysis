"""Registro imutável de sinais em Parquet (append-only). Regras e cadeia de hash: `transformers/signal_registry.py`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..transformers.signal_registry import SIGNAL_LOG_SCHEMA, chain_rows, verify_chain
from .parquet_loader import write_parquet
from .state_store import signal_log_path


class LogIntegrityError(RuntimeError):
    """A cadeia de hash do registro de sinais não confere: o passado foi alterado."""


def read_signal_log(path: Path | None = None) -> pd.DataFrame:
    p = path or signal_log_path()
    if not p.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in SIGNAL_LOG_SCHEMA.items()})
    return pd.read_parquet(p).astype(SIGNAL_LOG_SCHEMA)


def append_signal_log(rows: pd.DataFrame, path: Path | None = None) -> int:
    """Acrescenta as linhas novas (dia, moeda ainda ausente) e devolve quantas entraram. Antes de gravar, confere a cadeia
    existente; se estiver quebrada, levanta `LogIntegrityError` e nada é gravado."""
    p = path or signal_log_path()
    current = read_signal_log(p)
    problems = verify_chain(current)
    if problems:
        raise LogIntegrityError("registro de sinais adulterado, nada foi gravado: " + "; ".join(problems[:3]))
    fresh = chain_rows(current, rows)
    if fresh.empty:
        return 0
    write_parquet(pd.concat([current, fresh], ignore_index=True) if not current.empty else fresh, p)
    return len(fresh)
