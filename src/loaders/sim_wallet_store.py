"""Decisões das carteiras simuladas na pasta de estado (repositório de estado), append-only.

Regras puras (cadeia de hash, chave, replay): `transformers/sim_wallet.py`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..transformers.sim_wallet import DECISION_SCHEMA, chain_rows, empty_log, verify_chain
from .parquet_loader import write_parquet
from .state_store import sim_decisions_path


class SimLogIntegrityError(RuntimeError):
    """A cadeia de hash das decisões simuladas não confere: o passado foi alterado."""


def read_decisions(path: Path | None = None) -> pd.DataFrame:
    p = path or sim_decisions_path()
    if not p.is_file():
        return empty_log()
    return pd.read_parquet(p).astype(DECISION_SCHEMA)


def append_decisions(rows: pd.DataFrame, path: Path | None = None) -> int:
    """Acrescenta as decisões novas (chave carteira, dia, moeda e lado ainda ausente); confere a cadeia antes e não grava nada
    se estiver quebrada. Devolve quantas entraram."""
    p = path or sim_decisions_path()
    current = read_decisions(p)
    problems = verify_chain(current)
    if problems:
        raise SimLogIntegrityError("registro de decisões simuladas adulterado, nada foi gravado: " + "; ".join(problems[:3]))
    fresh = chain_rows(current, rows)
    if fresh.empty:
        return 0
    write_parquet(pd.concat([current, fresh], ignore_index=True) if not current.empty else fresh, p)
    return len(fresh)
