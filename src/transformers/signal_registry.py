"""Registro imutável de sinais: uma linha por moeda e dia de dados, com cadeia de hash.

Puro (CLAUDE.md §1). Cada execução do pipeline acrescenta o que foi mostrado ao usuário naquele dia (estágio, score,
classificação, alerta e a evidência estatística do COMPRAR) com a versão da configuração e do código. Nunca se reescreve o
passado: uma linha nova só entra se o par (dia, moeda) ainda não existe, e cada linha carrega o hash da anterior
(`prev_hash`) e o próprio (`row_hash`). Alterar ou apagar uma linha antiga quebra a cadeia e `verify_chain` acusa.

Este registro será o teste fora da amostra: o que foi publicado no dia, sem a possibilidade de ajustar depois.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Hashable, Mapping

import numpy as np
import pandas as pd

from .. import config

GENESIS = "0" * 64

SIGNAL_LOG_SCHEMA: dict[str, str] = {
    "day": "datetime64[ns, UTC]",       # dia (UTC) do último candle usado
    "symbol": "string",
    "run_ts": "datetime64[ns, UTC]",    # quando o pipeline rodou
    "stage": "string",                  # COMPRAR / PREPARAR / NEUTRO / INDISPONÍVEL (já com a exigência de evidência)
    "alert": "string",
    "uptrend": "bool",                  # regra SMA 200 ativa (moeda e BTC acima da SMA 200)
    "close": "float64",
    "score": "float64",
    "opportunity": "string",
    "selected": "bool",
    "candidate_rank": "Int64",
    "evidence_status": "string",        # VALIDADA / NAO_VALIDADA / SEM_EVIDENCIA / REVOGADA / NAO_AVALIADA
    "evidence_excess_7": "float64",
    "evidence_excess_30": "float64",
    "evidence_p_holm_30": "float64",
    "config_version": "string",
    "code_version": "string",
    "prev_hash": "string",
    "row_hash": "string",
}
PAYLOAD_COLUMNS: tuple[str, ...] = tuple(c for c in SIGNAL_LOG_SCHEMA if c not in ("prev_hash", "row_hash"))

_CONFIG_NAMES: tuple[str, ...] = (
    "RECOMMENDED", "MAX_UNIVERSE_SIZE", "MIN_HISTORY_DAYS", "MIN_AVG_QUOTE_VOLUME_USD", "REGIME_SYMBOL", "FEE_PER_SIDE",
    "SCORE_WEIGHTS", "SCORE_STRONG", "SCORE_MODERATE", "MIN_CONDITIONS", "ENABLED_SETUPS", "SETUP_PARAMS", "MAX_VOLATILITY",
    "HIGH_VOLATILITY", "MAX_DRAWDOWN_180D", "MAX_STRETCH", "MAX_RSI_ENTRY", "REGIME_FILTER", "MAX_POSITIONS",
    "MAX_ALLOCATION_PCT", "TARGET_VOL_PER_POSITION", "SPREAD_TIERS", "SLIPPAGE", "EXECUTION_MODEL_VERSION",
    "VALIDATION_HORIZONS", "VALIDATION_ALPHA", "VALIDATION_MIN_INDEPENDENT", "HOLDOUT_START", "DEVELOPMENT_END",
)


def config_version() -> str:
    """Impressão digital curta dos parâmetros de `config.py` que mudam o sinal, a seleção e o aporte."""
    values = {n: getattr(config, n, None) for n in _CONFIG_NAMES}
    text = json.dumps(values, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _cell(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA or value is pd.NaT:
        return ""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def row_hash(prev_hash: str, row: Mapping[Hashable, object]) -> str:
    payload = "|".join(_cell(row[c]) for c in PAYLOAD_COLUMNS)
    return hashlib.sha256(f"{prev_hash}|{payload}".encode("utf-8")).hexdigest()


def build_rows(
    signals: pd.DataFrame, evidence: pd.DataFrame, *, run_ts: pd.Timestamp, code_version: str, version: str | None = None
) -> pd.DataFrame:
    """Linhas do dia a partir de `daily_signals` (já com a exigência de evidência aplicada) e da tabela de evidência.
    Sem `prev_hash`/`row_hash`: quem acrescenta ao registro (`chain_rows`) calcula a cadeia."""
    ev = evidence.set_index("symbol") if not evidence.empty else pd.DataFrame(columns=["status"]).set_index(pd.Index([], name="symbol"))

    def pick(column: str) -> pd.Series:
        if column not in ev.columns:
            return pd.Series(np.nan, index=signals.index, dtype="float64")
        return signals["symbol"].map(ev[column]).astype("float64")

    status = signals["symbol"].map(ev["status"]).astype("string").fillna("NAO_AVALIADA") if "status" in ev.columns else pd.Series("NAO_AVALIADA", index=signals.index, dtype="string")
    out = pd.DataFrame(
        {
            "day": signals["timestamp"].dt.floor("D"),
            "symbol": signals["symbol"],
            "run_ts": run_ts,
            "stage": signals["stage"],
            "alert": signals["alert"],
            "uptrend": signals["uptrend"].fillna(False).astype(bool),
            "close": signals["close"],
            "score": signals["score"],
            "opportunity": signals["opportunity"],
            "selected": signals["selected"].fillna(False).astype(bool),
            "candidate_rank": signals["candidate_rank"],
            "evidence_status": status,
            "evidence_excess_7": pick("excess_7"),
            "evidence_excess_30": pick("excess_30"),
            "evidence_p_holm_30": pick("p_holm_30"),
            "config_version": version if version is not None else config_version(),
            "code_version": code_version,
        }
    )
    return out.astype({c: t for c, t in SIGNAL_LOG_SCHEMA.items() if c in out.columns}).reset_index(drop=True)


def chain_rows(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta `new` ao fim de `existing`: ignora (dia, moeda) que já existe (o passado não é reescrito) e encadeia os
    hashes a partir do último registro. Devolve só as linhas realmente novas, já com `prev_hash` e `row_hash`."""
    seen = set(zip(existing["day"], existing["symbol"], strict=True)) if not existing.empty else set()
    fresh = new[[(d, s) not in seen for d, s in zip(new["day"], new["symbol"], strict=True)]]
    fresh = fresh.sort_values(["day", "symbol"], ignore_index=True)
    prev = str(existing["row_hash"].iloc[-1]) if not existing.empty else GENESIS
    hashes, previous = [], []
    for row in fresh.to_dict("records"):
        previous.append(prev)
        prev = row_hash(prev, row)
        hashes.append(prev)
    return fresh.assign(prev_hash=pd.Series(previous, dtype="string"), row_hash=pd.Series(hashes, dtype="string")).astype(
        {c: t for c, t in SIGNAL_LOG_SCHEMA.items() if c in fresh.columns or c in ("prev_hash", "row_hash")}
    )[list(SIGNAL_LOG_SCHEMA)]


def verify_chain(log: pd.DataFrame) -> list[str]:
    """Problemas da cadeia (lista vazia = íntegra): hash que não confere, elo quebrado ou (dia, moeda) repetido."""
    problems: list[str] = []
    prev = GENESIS
    for i, row in enumerate(log.to_dict("records")):
        if str(row["prev_hash"]) != prev:
            problems.append(f"linha {i}: elo quebrado (prev_hash não é o hash da linha anterior)")
        if row_hash(str(row["prev_hash"]), row) != str(row["row_hash"]):
            problems.append(f"linha {i}: o conteúdo não bate com o row_hash (linha alterada)")
        prev = str(row["row_hash"])
    dup = log.duplicated(["day", "symbol"], keep=False)
    if dup.any():
        problems.append(f"{int(dup.sum())} linhas com (dia, moeda) repetido")
    return problems[:20]
