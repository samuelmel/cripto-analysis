"""Qualidade dos dados de preço: auditoria dos candles, limpeza e disponibilidade de cada moeda.

Puro (CLAUDE.md §1): a data de referência ("hoje") é parâmetro, injetado pelo entrypoint.

    audit_candles   relata o que há de errado nos candles da base (duplicados, fora de ordem,
                    preço nulo/NaN/inf/<= 0, fontes misturadas, lacunas de dias)
    clean_candles   remove o que não é utilizável (preço inválido e duplicados) e ordena
    availability    decide se cada moeda tem dado confiável hoje: candle recente, histórico
                    suficiente para a SMA 200 e, para as demais moedas, filtro de mercado (BTC) disponível
    mark_unavailable  passa o estágio de quem não tem dado confiável para INDISPONÍVEL, com o motivo

Dado desatualizado nunca gera sinal "atual": o candle do dia D fecha às 00:00 de D+1, então em `today`
o último candle fechado esperado é o de `today - 1 dia`; mais velho que isso (além de `max_stale_days`)
é desatualizado.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from .anomaly_detector import STAGE_UNAVAILABLE

PRICE_COLUMNS = ("open", "high", "low", "close")

ISSUE_SCHEMA: dict[str, str] = {"symbol": "string", "kind": "string", "count": "int64", "detail": "string"}
AVAILABILITY_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "available": "bool",
    "reason": "string",
    "last_ts": "datetime64[ns, UTC]",
}

ISSUE_DUPLICATE = "duplicados"
ISSUE_UNORDERED = "fora_de_ordem"
ISSUE_BAD_PRICE = "preco_invalido"
ISSUE_MIXED_SOURCES = "fontes_misturadas"
ISSUE_GAPS = "lacunas"


def _invalid_price(candles: pd.DataFrame) -> pd.Series:
    """True onde algum preço presente (open/high/low/close) é nulo, NaN, infinito ou <= 0."""
    cols = [c for c in PRICE_COLUMNS if c in candles.columns]
    values = candles[cols].apply(pd.to_numeric, errors="coerce")
    finite = pd.DataFrame(np.isfinite(values.to_numpy(dtype="float64")), index=values.index, columns=cols)
    valid: pd.Series = (finite & values.gt(0)).all(axis=1)
    return ~valid


def audit_candles(candles: pd.DataFrame) -> pd.DataFrame:
    """Problemas encontrados nos candles, um por (symbol, tipo), no formato de ISSUE_SCHEMA. Vazio se não há."""
    if candles.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in ISSUE_SCHEMA.items()})

    symbol = candles["symbol"].astype("string")
    rows: list[pd.DataFrame] = []

    def add(kind: str, counts: pd.Series, detail: str) -> None:
        counts = counts[counts.gt(0)]
        if not counts.empty:
            rows.append(
                pd.DataFrame(
                    {"symbol": counts.index.astype("string"), "kind": kind, "count": counts.to_numpy(dtype="int64"), "detail": detail}
                )
            )

    dup = candles.duplicated(["symbol", "timestamp"], keep="first")
    add(ISSUE_DUPLICATE, dup.groupby(symbol).sum(), "candles repetidos para o mesmo dia")

    previous = candles.groupby("symbol", sort=False)["timestamp"].shift(1)
    add(ISSUE_UNORDERED, candles["timestamp"].lt(previous).groupby(symbol).sum(), "candle anterior ao candle da linha de cima")

    add(ISSUE_BAD_PRICE, _invalid_price(candles).groupby(symbol).sum(), "preço nulo, NaN, infinito ou <= 0")

    if "source" in candles.columns:
        sources = candles.groupby("symbol")["source"].nunique()
        add(ISSUE_MIXED_SOURCES, sources.sub(1), "candles de mais de uma fonte na mesma moeda")

    days = candles.assign(day=candles["timestamp"].dt.floor("D")).groupby("symbol")["day"]
    span = (days.max() - days.min()).dt.days + 1
    add(ISSUE_GAPS, span - days.nunique(), "dias sem candle entre o primeiro e o último")

    return pd.concat(rows, ignore_index=True).astype(ISSUE_SCHEMA) if rows else pd.DataFrame(
        {c: pd.Series(dtype=t) for c, t in ISSUE_SCHEMA.items()}
    )


def clean_candles(candles: pd.DataFrame) -> pd.DataFrame:
    """Sem candles de preço inválido nem duplicados (fica o último de cada dia), ordenado por moeda e dia."""
    if candles.empty:
        return candles
    ok = candles[~_invalid_price(candles)]
    ok = ok.drop_duplicates(["symbol", "timestamp"], keep="last")
    return ok.sort_values(["symbol", "timestamp"], ignore_index=True)


def availability(
    history: pd.DataFrame,
    symbols: tuple[str, ...],
    today: pd.Timestamp,
    *,
    regime_symbol: str = config.REGIME_SYMBOL,
    max_stale_days: int = config.MAX_STALE_DAYS,
) -> pd.DataFrame:
    """Se cada moeda de `symbols` tem dado confiável hoje (AVAILABILITY_SCHEMA).

    `history`: saída de `classify_history` (precisa de symbol, timestamp e sma_200).
    """
    expected = today.floor("D") - pd.Timedelta(days=1)
    last = history.sort_values(["symbol", "timestamp"]).groupby("symbol", sort=False).tail(1)
    table = (
        pd.DataFrame({"symbol": pd.Series(list(symbols), dtype="string")})
        .merge(last[["symbol", "timestamp", "sma_200"]].astype({"symbol": "string"}), on="symbol", how="left")
        .rename(columns={"timestamp": "last_ts"})
    )
    lag = (expected - table["last_ts"]).dt.days
    shown = table["last_ts"].dt.strftime("%d/%m/%Y")
    own = pd.Series(
        np.select(
            [table["last_ts"].isna(), lag.gt(max_stale_days), table["sma_200"].isna()],
            [
                "sem candles na base",
                "dado desatualizado: último candle em " + shown + " (" + lag.astype("string") + " dias de atraso)",
                "histórico insuficiente: menos de 200 dias para calcular a média",
            ],
            default="",
        ),
        index=table.index,
        dtype="string",
    )
    regime_reason = own[table["symbol"].eq(regime_symbol)]
    name = regime_symbol.split("/")[0]
    if regime_reason.empty:
        market = f"filtro de mercado ({name}) sem dados"
    elif regime_reason.iloc[0] != "":
        market = f"filtro de mercado ({name}) indisponível: {regime_reason.iloc[0]}"
    else:
        market = ""
    reason = own.where(own.ne("") | table["symbol"].eq(regime_symbol), market)
    out = table.assign(available=reason.eq(""), reason=reason.mask(reason.eq(""), pd.NA))
    return out[list(AVAILABILITY_SCHEMA)].astype(AVAILABILITY_SCHEMA)


def mark_unavailable(snapshot: pd.DataFrame, available: pd.DataFrame) -> pd.DataFrame:
    """Estágio INDISPONÍVEL (com `stage_reason`) para quem não tem dado confiável; sem pânico nem tendência."""
    info = available[["symbol", "available", "reason"]].rename(columns={"reason": "unavailable_reason"})
    out = snapshot.merge(info.astype({"symbol": "string"}), on="symbol", how="left")
    bad = ~out["available"].fillna(True).astype(bool)
    out["stage"] = out["stage"].mask(bad, STAGE_UNAVAILABLE)
    out["stage_reason"] = out["unavailable_reason"].where(bad, pd.NA).astype("string")
    out["panic"] = out["panic"] & ~bad
    out["uptrend"] = out["uptrend"] & ~bad
    return out.drop(columns=["available", "unavailable_reason"])
