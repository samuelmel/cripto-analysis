"""Alertas de virada: compara o snapshot de hoje com o do último dia salvo.

Puro (CLAUDE.md §1). O histórico é lido/escrito por `src.loaders.history_store`.

    alert = "COMPRAR AGORA"   estágio virou COMPRAR hoje (ontem não era)
    alert = "VENDER AGORA"    estava em COMPRAR e deixou de estar (fechou abaixo da SMA 200, ou o BTC fechou)
    alert = "NO RADAR"        entrou em PREPARAR hoje (ontem era NEUTRO ou não existia)
    alert = "SAIU DO RADAR"   estava em PREPARAR e voltou a NEUTRO
    alert = <NA>              sem mudança relevante, ou moeda INDISPONÍVEL (dado velho nunca gera alerta)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .anomaly_detector import OUTPUT_SCHEMA, STAGE_BUY, STAGE_NEUTRAL, STAGE_UNAVAILABLE, STAGE_WATCH

ALERT_BUY = "COMPRAR AGORA"
ALERT_WATCH = "NO RADAR"
ALERT_SELL = "VENDER AGORA"
ALERT_EXIT = "SAIU DO RADAR"

DAILY_SCHEMA: dict[str, str] = {**OUTPUT_SCHEMA, "prev_stage": "string", "alert": "string"}

_STAGE_ORDER = {STAGE_BUY: 0, STAGE_WATCH: 1, STAGE_NEUTRAL: 2, STAGE_UNAVAILABLE: 3}


def compare_with_previous(today: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    """Adiciona `prev_stage` e `alert` ao snapshot de `anomaly_detector.detect`.

    `previous`: snapshot do último dia salvo (qualquer schema com `symbol` e `stage`) ou None.
    Ordenado por alerta de compra, depois estágio, depois distância ao preço médio de 200 dias (maior primeiro).
    """
    prev = (
        previous[["symbol", "stage"]].rename(columns={"stage": "prev_stage"})
        if previous is not None and not previous.empty
        else pd.DataFrame({"symbol": pd.Series(dtype="string"), "prev_stage": pd.Series(dtype="string")})
    )
    out = today.merge(prev.astype({"symbol": "string", "prev_stage": "string"}), on="symbol", how="left")

    stage = out["stage"]
    prev_stage = out["prev_stage"].fillna(STAGE_NEUTRAL)
    out["alert"] = np.select(
        [
            stage.eq(STAGE_BUY) & prev_stage.ne(STAGE_BUY),
            stage.ne(STAGE_BUY) & stage.ne(STAGE_UNAVAILABLE) & prev_stage.eq(STAGE_BUY),
            stage.eq(STAGE_WATCH) & prev_stage.eq(STAGE_NEUTRAL),
            stage.eq(STAGE_NEUTRAL) & prev_stage.eq(STAGE_WATCH),
        ],
        [ALERT_BUY, ALERT_SELL, ALERT_WATCH, ALERT_EXIT],
        default="",
    )
    out = out[list(DAILY_SCHEMA)].astype(DAILY_SCHEMA)
    out["alert"] = out["alert"].replace("", pd.NA)

    keys = pd.DataFrame(
        {
            "buy_alert": out["alert"].eq(ALERT_BUY).fillna(False).astype(int),
            "distance": (out["close"] / out["sma_200"]).fillna(-np.inf),
            "stage_rank": out["stage"].map(_STAGE_ORDER).astype(int),
        }
    )
    order = np.lexsort((-keys["distance"].to_numpy(), keys["stage_rank"].to_numpy(), -keys["buy_alert"].to_numpy()))
    return out.iloc[order].reset_index(drop=True)
