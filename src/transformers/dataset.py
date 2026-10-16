"""Identidade e trilha de alterações dos conjuntos de dados: fingerprint, manifesto por moeda e revisões de candles.

Puro (CLAUDE.md §1). Serve para que cada experimento registre exatamente quais dados usou (hash) e para que uma
correção de dado na fonte nunca substitua o valor antigo em silêncio (`candle_revisions` gera o evento).

O fingerprint é o SHA-256 dos hashes por linha do pandas (`hash_pandas_object`) sobre o recorte ordenado e
canônico das colunas escolhidas: mesmo conteúdo = mesmo hash, independente da ordem das linhas ou do arquivo.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np
import pandas as pd

CANDLE_VALUE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "quote_volume", "trades")
CANDLE_KEYS: tuple[str, ...] = ("symbol", "timestamp")

REVISION_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "timestamp": "datetime64[ns, UTC]",   # candle revisado
    "column": "string",
    "old_value": "float64",
    "new_value": "float64",
    "ingested_at": "datetime64[ns, UTC]", # quando a nova versão foi gravada (injetado pelo entrypoint)
}

DATASET_MANIFEST_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "rows": "int64",
    "first_ts": "datetime64[ns, UTC]",
    "last_ts": "datetime64[ns, UTC]",
    "sha256": "string",
}


def frame_fingerprint(df: pd.DataFrame, keys: Sequence[str], columns: Sequence[str]) -> str:
    """SHA-256 do conteúdo de `columns` (ordenado por `keys`). Colunas ausentes entram como nulas."""
    cols = list(dict.fromkeys([*keys, *columns]))
    frame = df.reindex(columns=cols).sort_values(list(keys), kind="mergesort", ignore_index=True)
    digest = hashlib.sha256()
    digest.update(("|".join(cols) + f"#{len(frame)}").encode())
    if len(frame):
        digest.update(pd.util.hash_pandas_object(frame, index=False).to_numpy(dtype="uint64").tobytes())
    return digest.hexdigest()


def candle_fingerprint(candles: pd.DataFrame) -> str:
    """Fingerprint de um conjunto de candles padronizados (chaves + valores de CANDLE_VALUE_COLUMNS)."""
    return frame_fingerprint(candles, CANDLE_KEYS, CANDLE_VALUE_COLUMNS)


def dataset_manifest(candles: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por moeda: linhas, primeiro e último candle e fingerprint (DATASET_MANIFEST_SCHEMA)."""
    rows = [
        {
            "symbol": str(symbol),
            "rows": len(part),
            "first_ts": part["timestamp"].min(),
            "last_ts": part["timestamp"].max(),
            "sha256": candle_fingerprint(part),
        }
        for symbol, part in candles.groupby("symbol", observed=True, sort=True)
    ]
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in DATASET_MANIFEST_SCHEMA.items()})
    return pd.DataFrame(rows)[list(DATASET_MANIFEST_SCHEMA)].astype(DATASET_MANIFEST_SCHEMA)


def combined_fingerprint(manifest: pd.DataFrame) -> str:
    """Um hash para o conjunto inteiro, a partir dos SHA-256 por moeda de `dataset_manifest` (ordem alfabética)."""
    parts = manifest.sort_values("symbol")[["symbol", "sha256"]].astype(str)
    return hashlib.sha256("|".join(parts["symbol"] + ":" + parts["sha256"]).encode()).hexdigest()


def candle_revisions(old: pd.DataFrame | None, new: pd.DataFrame, ingested_at: pd.Timestamp) -> pd.DataFrame:
    """Valores de candles já gravados que a nova leitura altera (REVISION_SCHEMA, um registro por coluna mudada).

    Candle novo (sem versão anterior) não é revisão. Dois NaN são iguais; diferença relativa < 1e-12 também
    (ruído de representação, não correção de dado).
    """
    empty = pd.DataFrame({c: pd.Series(dtype=t) for c, t in REVISION_SCHEMA.items()})
    if old is None or old.empty or new.empty:
        return empty
    cols = [c for c in CANDLE_VALUE_COLUMNS if c in old.columns and c in new.columns]
    keys = list(CANDLE_KEYS)
    before = old.drop_duplicates(keys, keep="last").set_index(keys)[cols]
    after = new.drop_duplicates(keys, keep="last").set_index(keys)[cols]
    common = before.index.intersection(after.index)
    if common.empty:
        return empty
    a = before.loc[common].astype("float64")
    b = after.loc[common].astype("float64")
    av, bv = a.to_numpy(), b.to_numpy()
    same = (np.isnan(av) & np.isnan(bv)) | np.isclose(av, bv, rtol=1e-12, atol=0.0)
    if same.all():
        return empty
    rows, cols_at = np.nonzero(~same)
    out = pd.DataFrame(
        {
            "symbol": common.get_level_values(0)[rows].astype("string"),
            "timestamp": common.get_level_values(1)[rows],
            "column": pd.Series([cols[j] for j in cols_at], dtype="string"),
            "old_value": av[rows, cols_at],
            "new_value": bv[rows, cols_at],
            "ingested_at": ingested_at,
        }
    )
    return out[list(REVISION_SCHEMA)].astype(REVISION_SCHEMA).reset_index(drop=True)
