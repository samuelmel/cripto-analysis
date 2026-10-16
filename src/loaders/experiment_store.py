"""Registro de experimentos e tabelas da validação estatística, append-only, em Parquet.

    data/research/validation/registry.parquet   uma linha por experimento por execução (`experiments.REGISTRY_SCHEMA`)
    data/research/validation/<tabela>.parquet   resumo, dobras, cenários, variações, blocos, regimes, escolhas do
                                                walk-forward e retornos diários, todas com a coluna `run_id`

Nunca sobrescreve: gravar um `run_id` que já existe numa tabela é recusado (`DuplicateRunError`); uma execução nova
do mesmo experimento entra como linhas novas, com outro `run_id`. A escrita de cada arquivo é atômica
(`parquet_loader.write_parquet`). Nada aqui é versionado no Git (`/data/` está no .gitignore).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..transformers.experiments import REGISTRY_SCHEMA
from .parquet_loader import write_parquet

VALIDATION_DIR = Path("data/research/validation")


class DuplicateRunError(ValueError):
    """O run_id já foi gravado: resultados anteriores não são substituídos."""


def read_table(name: str, base: Path = VALIDATION_DIR) -> pd.DataFrame:
    path = base / f"{name}.parquet"
    if not path.is_file():
        if name == "registry":
            return pd.DataFrame({c: pd.Series(dtype=t) for c, t in REGISTRY_SCHEMA.items()})
        return pd.DataFrame({"run_id": pd.Series(dtype="string")})
    return pd.read_parquet(path)


def append_table(name: str, rows: pd.DataFrame, base: Path = VALIDATION_DIR) -> Path:
    """Acrescenta `rows` (com coluna run_id) à tabela; recusa run_id já existente."""
    if "run_id" not in rows.columns:
        raise ValueError("toda tabela da validação precisa da coluna run_id")
    existing = read_table(name, base)
    clash = set(rows["run_id"].astype(str)) & set(existing["run_id"].astype(str))
    if clash:
        raise DuplicateRunError(f"{name}: run_id já gravado ({sorted(clash)}); nada foi sobrescrito")
    merged = rows if existing.empty else pd.concat([existing, rows], ignore_index=True)
    if name == "registry":
        merged = merged.astype(REGISTRY_SCHEMA)
    return write_parquet(merged, base / f"{name}.parquet", compression="zstd")
