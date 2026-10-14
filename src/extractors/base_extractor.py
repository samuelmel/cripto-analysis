"""Contrato comum dos extratores (padrão Adapter).

Cada fonte externa tem uma API diferente; cada adaptador traduz a sua para a mesma interface,
`extract(start, end) -> DataFrame`, e o restante do ETL (transformers/loaders) só conhece o
formato padronizado abaixo.

Formato padronizado (long por timestamp × symbol):
    timestamp   datetime64[ns, UTC]   início do período da observação
    source      string                identificador da fonte (ex.: "binance")
    symbol      string                ativo (ex.: "BTC/USDT"); "MARKET" para séries globais
    <valores>   colunas declaradas em `value_columns` de cada adaptador, na ordem declarada

Garantias de `extract`: chaves sem nulos, (timestamp, symbol) único, ordenado por symbol e
timestamp, dtypes conforme declarados, nenhuma coluna além das chaves e dos valores.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar

import pandas as pd

KEY_COLUMNS: dict[str, str] = {
    "timestamp": "datetime64[ns, UTC]",
    "source": "string",
    "symbol": "string",
}
MARKET_SYMBOL = "MARKET"


class ExtractorError(RuntimeError):
    """Falha de extração (rede, resposta inválida ou violação do formato padronizado)."""


class BaseExtractor(ABC):
    """Template method: `fetch` (I/O) -> `to_frame` (parse) -> `standardize` (contrato)."""

    source: ClassVar[str]
    # nome da coluna -> dtype pandas. Define o schema de saída específico do adaptador.
    value_columns: ClassVar[dict[str, str]]

    def extract(self, start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
        """Extrai o intervalo [start, end) e devolve o DataFrame padronizado."""
        end = end or datetime.now(timezone.utc)
        raw = self.fetch(start, end)
        return self.standardize(self.to_frame(raw))

    @abstractmethod
    def fetch(self, start: datetime | None, end: datetime) -> Any:
        """Busca os dados brutos da fonte (I/O apenas, sem parse). `start=None` = histórico completo."""

    @abstractmethod
    def to_frame(self, raw: Any) -> pd.DataFrame:
        """Converte o payload bruto em DataFrame com `timestamp`, `symbol` e as `value_columns`."""

    @classmethod
    def schema(cls) -> dict[str, str]:
        return {**KEY_COLUMNS, **cls.value_columns}

    def standardize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Impõe o formato padronizado. Lança ExtractorError se o adaptador violar o contrato."""
        schema = self.schema()
        if df.empty:
            return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})

        out = df.assign(source=self.source)
        missing = set(schema) - set(out.columns)
        if missing:
            raise ExtractorError(f"{self.source}: colunas ausentes {sorted(missing)}")

        out = out[list(schema)]
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
        out = out.astype(schema)

        if out[list(KEY_COLUMNS)].isna().any().any():
            raise ExtractorError(f"{self.source}: chaves nulas em timestamp/source/symbol")
        out = out.drop_duplicates(["timestamp", "symbol"], keep="last")
        return out.sort_values(["symbol", "timestamp"], ignore_index=True)
