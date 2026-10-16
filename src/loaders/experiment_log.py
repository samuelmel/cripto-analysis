"""Registro append-only de experimentos de pesquisa (Fase 5): nunca sobrescreve um resultado anterior.

Contrato: `append_experiment` acrescenta uma linha. Se o `experiment_id` já existe e o `results_digest` é igual, a
execução é uma REPRODUÇÃO (nada é gravado). Se o ID existe e o digest difere, levanta `ExperimentConflict` e o
registro permanece intacto. A escrita é atômica (`write_parquet`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from .parquet_loader import write_parquet

REGISTRY_PATH = Path("data/research/experiments.parquet")

REGISTRY_SCHEMA: dict[str, str] = {
    "experiment_id": "string",
    "created_at": "datetime64[ns, UTC]",
    "code_version": "string",         # HEAD do Git ("desconhecido" se indisponível)
    "working_tree_dirty": "bool",     # havia alterações não commitadas na execução
    "data_fingerprint": "string",
    "classifier_version": "string",
    "classifier_params_hash": "string",
    "policy_version": "string",
    "universe": "string",
    "period_start": "datetime64[ns, UTC]",
    "period_end": "datetime64[ns, UTC]",
    "seed": "int64",
    "bootstrap_block": "int64",
    "bootstrap_resamples": "int64",
    "n_policies": "int64",
    "n_variants": "int64",
    "n_hypotheses": "int64",
    "config_json": "string",
    "results_digest": "string",
    "results_file": "string",
    "status": "string",               # EXPLORATORIO: não existe teste prospectivo
    "limitations": "string",
}

NEW = "novo"
REPRODUCED = "reproduzido"


class ExperimentConflict(Exception):
    """Mesmo `experiment_id`, resultados diferentes: não é uma reprodução."""


def read_registry(path: Path = REGISTRY_PATH) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in REGISTRY_SCHEMA.items()})
    return pd.read_parquet(path).astype(REGISTRY_SCHEMA)


def append_experiment(record: Mapping[str, object], path: Path = REGISTRY_PATH) -> str:
    """Acrescenta o registro (`NEW`) ou confirma a reprodução (`REPRODUCED`). Conflito -> ExperimentConflict."""
    missing = set(REGISTRY_SCHEMA) - set(record)
    if missing:
        raise ValueError(f"registro incompleto, faltam: {sorted(missing)}")
    current = read_registry(path)
    same = current[current["experiment_id"].eq(str(record["experiment_id"]))]
    if not same.empty:
        if str(same["results_digest"].iloc[0]) == str(record["results_digest"]):
            return REPRODUCED
        raise ExperimentConflict(
            f"experimento {record['experiment_id']} já registrado com outros resultados "
            f"({same['results_digest'].iloc[0]} contra {record['results_digest']}); o registro não foi alterado"
        )
    row = pd.DataFrame([{c: record[c] for c in REGISTRY_SCHEMA}]).astype(REGISTRY_SCHEMA)
    write_parquet(pd.concat([current, row], ignore_index=True) if not current.empty else row, path)
    return NEW
