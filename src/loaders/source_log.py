"""Registro da última atualização de cada fonte: data/market/source_log/data.parquet.

Uma linha por (source, scope): a mais recente. `scope` é o símbolo (ex.: "BTC/USDT") ou "MARKET".
Guarda só status e mensagem de erro curta, nunca cabeçalhos nem chaves.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .market_store import MARKET_DIR
from .parquet_loader import write_parquet

SOURCE_LOG_SCHEMA: dict[str, str] = {
    "source": "string",
    "scope": "string",
    "updated_at": "datetime64[ns, UTC]",  # quando rodamos a atualização
    "status": "string",                   # "ok" ou "erro"
    "rows": "int64",                      # linhas novas obtidas
    "last_data_ts": "datetime64[ns, UTC]",  # último dado da fonte nessa execução (nulo se não veio nada)
    "detail": "string",
}

_MAX_DETAIL = 300


def _path(base: Path) -> Path:
    return base / "source_log" / "data.parquet"


def _history_path(base: Path) -> Path:
    return base / "source_log" / "history.parquet"


def read_source_history(base: Path = MARKET_DIR) -> pd.DataFrame:
    """Todas as atualizações já registradas (append-only), não só a última de cada fonte."""
    path = _history_path(base)
    if not path.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in SOURCE_LOG_SCHEMA.items()})
    return pd.read_parquet(path).astype(SOURCE_LOG_SCHEMA)


def read_source_log(base: Path = MARKET_DIR) -> pd.DataFrame:
    path = _path(base)
    if not path.is_file():
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in SOURCE_LOG_SCHEMA.items()})
    return pd.read_parquet(path).astype(SOURCE_LOG_SCHEMA)


def write_source_log(events: pd.DataFrame, base: Path = MARKET_DIR) -> Path:
    """Upsert por (source, scope): a execução mais recente substitui a anterior em `data.parquet`; todas as
    execuções ficam também em `history.parquet` (append-only), para auditar falhas passadas de coleta."""
    new = events.assign(
        detail=events["detail"].astype("string").str.slice(0, _MAX_DETAIL),
        # Se todas as fontes falharem, a coluna só tem NaT (sem fuso) e o astype para UTC quebraria.
        updated_at=pd.to_datetime(events["updated_at"], utc=True),
        last_data_ts=pd.to_datetime(events["last_data_ts"], utc=True),
    )[list(SOURCE_LOG_SCHEMA)]
    new = new.astype(SOURCE_LOG_SCHEMA)
    history = pd.concat([read_source_history(base), new], ignore_index=True).astype(SOURCE_LOG_SCHEMA)
    write_parquet(history.drop_duplicates(keep="first"), _history_path(base), compression="zstd")
    old = read_source_log(base)
    merged = new if old.empty else pd.concat([old, new], ignore_index=True)
    merged = merged.drop_duplicates(["source", "scope"], keep="last").sort_values(["source", "scope"], ignore_index=True)
    return write_parquet(merged, _path(base), compression="zstd")
