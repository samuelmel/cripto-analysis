"""Registro de experimentos: identidade determinística, configuração completa e proteção contra mistura de motores.

Puro (CLAUDE.md §1): monta as linhas; quem grava (append-only, nunca sobrescreve) é `loaders/experiment_store.py`.
A data da execução é parâmetro (injetada pelo entrypoint).

Identidade. `experiment_id` = SHA-256 (16 hex) do JSON canônico da especificação (estratégia, parâmetros, período,
universo, referência, versão do motor, custos, banda, deslistagem, cenário, protocolo e fingerprint dos dados). A
mesma especificação sobre os mesmos dados tem sempre o mesmo id; mudar qualquer coisa (inclusive os dados) muda o
id. `run_id` identifica a execução (várias execuções do mesmo experimento são linhas diferentes, nunca uma por
cima da outra), e `reproduces` diz se os números coincidem com os de uma execução anterior do mesmo id.

Mistura de motores. `assert_comparable` recusa uma tabela de comparação com versões de motor, protocolo, dados,
período ou custos diferentes: resultados de motores distintos nunca entram lado a lado sem identificação.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .costs import CostModel

PROTOCOL_VERSION = "wf-v1"

STATUS_VALID = "VALIDO"
STATUS_INVALID = "INVALIDO"
STATUS_PENDING = "AGUARDANDO_DADOS"

REGISTRY_SCHEMA: dict[str, str] = {
    "run_id": "string",
    "run_ts": "datetime64[ns, UTC]",
    "experiment_id": "string",
    "family": "string",
    "strategy": "string",
    "params_json": "string",            # JSON canônico (texto dentro do Parquet; o armazenamento é Parquet)
    "universe": "string",
    "benchmark": "string",
    "scenario": "string",
    "period_start": "datetime64[ns, UTC]",
    "period_end": "datetime64[ns, UTC]",
    "data_status": "string",            # EXPLORADO_NO_DESENVOLVIMENTO / PROSPECTIVO
    "execution_version": "string",
    "protocol_version": "string",
    "costs_json": "string",
    "rebalance_band": "float64",
    "delist_recovery": "float64",
    "data_fingerprint": "string",
    "config_fingerprint": "string",     # regras das estratégias (seleção, alocação, saídas) usadas
    "metrics_json": "string",
    "validation_json": "string",        # IC, p-valores, classificação
    "category": "string",
    "status": "string",                 # VALIDO / INVALIDO / AGUARDANDO_DADOS
    "limitations": "string",
    "reproduces": "boolean",            # NA = primeira execução deste id
}


class MixedExperimentError(ValueError):
    """Tentativa de comparar experimentos com premissas, motores ou dados diferentes."""


def _plain(value: object) -> object:
    """Valor serializável e estável: floats arredondados a 12 algarismos, NaN como None, datas em ISO."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        v = float(value)
        return None if not math.isfinite(v) else float(f"{v:.12g}")
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    return str(value)


def canonical_json(value: object) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: object, length: int = 16) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


@dataclass(frozen=True)
class ExperimentSpec:
    family: str
    strategy: str
    params: Mapping[str, object]
    universe: str
    benchmark: str
    scenario: str
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    data_status: str
    execution_version: str
    costs: CostModel
    rebalance_band: float
    delist_recovery: float
    data_fingerprint: str
    config_fingerprint: str
    protocol_version: str = PROTOCOL_VERSION
    limitations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def experiment_id(self) -> str:
        identity = {k: v for k, v in dataclasses.asdict(self).items() if k != "limitations"}
        return fingerprint(identity)


def registry_rows(
    entries: Sequence[tuple[ExperimentSpec, Mapping[str, object], Mapping[str, object], str, str]],
    run_id: str,
    run_ts: pd.Timestamp,
    previous: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Linhas do registro. `entries`: (especificação, métricas, validação, categoria, status).

    `previous`: o registro já gravado; `reproduces` compara as métricas com a execução mais recente do mesmo id.
    """
    last_metrics: dict[str, str] = {}
    if previous is not None and not previous.empty:
        ordered = previous.sort_values("run_ts")
        last_metrics = dict(zip(ordered["experiment_id"].astype(str), ordered["metrics_json"].astype(str), strict=True))
    rows: list[dict[str, object]] = []
    for spec, metrics, validation, category, status in entries:
        eid = spec.experiment_id
        m_json = canonical_json(metrics)
        rows.append({
            "run_id": run_id, "run_ts": run_ts, "experiment_id": eid, "family": spec.family, "strategy": spec.strategy,
            "params_json": canonical_json(spec.params), "universe": spec.universe, "benchmark": spec.benchmark,
            "scenario": spec.scenario, "period_start": spec.period_start, "period_end": spec.period_end,
            "data_status": spec.data_status, "execution_version": spec.execution_version,
            "protocol_version": spec.protocol_version, "costs_json": canonical_json(spec.costs),
            "rebalance_band": spec.rebalance_band, "delist_recovery": spec.delist_recovery,
            "data_fingerprint": spec.data_fingerprint, "config_fingerprint": spec.config_fingerprint,
            "metrics_json": m_json, "validation_json": canonical_json(validation), "category": category,
            "status": status, "limitations": "; ".join(spec.limitations),
            "reproduces": (last_metrics[eid] == m_json) if eid in last_metrics else pd.NA,
        })
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in REGISTRY_SCHEMA.items()})
    out = pd.DataFrame(rows)[list(REGISTRY_SCHEMA)]
    for col in ("run_ts", "period_start", "period_end"):
        out[col] = pd.to_datetime(out[col], utc=True)
    return out.astype(REGISTRY_SCHEMA)


COMPARABLE_KEYS: tuple[str, ...] = (
    "execution_version", "protocol_version", "data_fingerprint", "period_start", "period_end", "costs_json",
    "delist_recovery",
)


def assert_comparable(rows: pd.DataFrame, keys: Sequence[str] = COMPARABLE_KEYS) -> None:
    """Falha se as linhas (uma tabela de comparação) não compartilham motor, protocolo, dados, período e custos."""
    for key in keys:
        values: list[str] = sorted(set(rows[key].astype(str))) if key in rows.columns else []
        if len(values) > 1:
            raise MixedExperimentError(f"comparação com '{key}' diferente entre linhas: {values}")
