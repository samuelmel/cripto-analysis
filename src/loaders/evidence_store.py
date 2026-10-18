"""Leitura da evidência estatística do COMPRAR (`evidence/signal_evidence.parquet`, versionada e gerada por
`research/signal_evidence_study.py`). Arquivo ausente ou ilegível = tabela vazia: nenhuma moeda validada (falha fechada)."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..transformers.entry_live import empty_levels
from ..transformers.entry_study import LEVEL_SCHEMA
from ..transformers.signal_validation import EVIDENCE_SCHEMA

EVIDENCE_PATH = Path("evidence/signal_evidence.parquet")

logger = logging.getLogger(__name__)


def empty_evidence() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in EVIDENCE_SCHEMA.items()})


def read_signal_evidence(path: Path = EVIDENCE_PATH) -> pd.DataFrame:
    if not path.is_file():
        return empty_evidence()
    try:
        frame = pd.read_parquet(path)
        return frame[list(EVIDENCE_SCHEMA)].astype(EVIDENCE_SCHEMA)
    except (OSError, KeyError, ValueError) as exc:
        logger.error("evidência do COMPRAR ilegível (%s); nenhuma moeda será validada: %s", path, exc)
        return empty_evidence()


ENTRY_LEVELS_PATH = Path("evidence/entry_signals/entry_signal_levels.parquet")


def read_entry_levels(path: Path = ENTRY_LEVELS_PATH) -> pd.DataFrame:
    """Níveis dos sinais de entrada (`research/entry_signal_study.py`). Ausente ou ilegível: tabela vazia, nenhuma
    combinação conta (falha fechada: sem COMPRAR e sem lista de observação)."""
    if not path.is_file():
        return empty_levels()
    try:
        frame = pd.read_parquet(path)
        return frame[list(LEVEL_SCHEMA)].astype(LEVEL_SCHEMA)
    except (OSError, KeyError, ValueError) as exc:
        logger.error("níveis dos sinais de entrada ilegíveis (%s); nenhum sinal será usado: %s", path, exc)
        return empty_levels()


EXIT_RULES_PATH = Path("evidence/exit_rules.parquet")


def read_exit_rules(path: Path = EXIT_RULES_PATH) -> pd.DataFrame:
    """O que cada regra de saída fez no backtest (`research/exit_rules_study.py`). Ausente: tabela vazia (sem texto histórico)."""
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError) as exc:
        logger.error("tabela das regras de saída ilegível (%s): %s", path, exc)
        return pd.DataFrame()
