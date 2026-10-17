"""Continuidade das séries de preço: divide um par em segmentos quando o ativo mudou sem mudar de nome.

Puro (CLAUDE.md §1). Critério e justificativa: docs/data_continuity.md (fixados antes de refazer os testes).
Uma quebra é uma lacuna de candles diários (`gap_days` ou mais entre dois candles seguidos) ou um salto de preço para
cima maior que `max_up_jump` vezes de um dia para o outro. Queda grande não é quebra (perda real, evita viés de
sobrevivência). Cada segmento depois do primeiro vira um instrumento novo, `BASE#k/QUOTE`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config

REASON_GAP = "LACUNA"
REASON_JUMP = "SALTO"
REASON_BOTH = "LACUNA+SALTO"
REPORT_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "segment_symbol": "string",
    "break_day": "datetime64[ns, UTC]",
    "gap_days": "int64",
    "price_ratio": "float64",
    "reason": "string",
}


@dataclass(frozen=True)
class ContinuityRules:
    gap_days: int = config.CONTINUITY_GAP_DAYS
    max_up_jump: float = config.CONTINUITY_MAX_UP_JUMP
    version: str = config.CONTINUITY_VERSION


def segment_symbol(symbol: str, k: int) -> str:
    """Nome do k-ésimo segmento (k >= 1) de um par: o primeiro mantém o nome original."""
    if k == 0:
        return symbol
    base, _, quote = symbol.partition("/")
    return f"{base}#{k + 1}/{quote}"


def split_discontinuities(
    candles: pd.DataFrame, rules: ContinuityRules = ContinuityRules()
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(candles com os pares divididos em segmentos, relatório das quebras). Não altera `candles`."""
    if candles.empty:
        return candles.copy(), pd.DataFrame({c: pd.Series(dtype=t) for c, t in REPORT_SCHEMA.items()})
    frame = candles.sort_values(["symbol", "timestamp"], kind="stable").reset_index(drop=True)
    by = frame.groupby("symbol", sort=False, observed=True)
    gap = by["timestamp"].diff().dt.days.fillna(0).astype("int64")
    ratio = (frame["close"] / by["close"].shift(1)).astype("float64")
    is_gap = gap.ge(rules.gap_days)
    is_jump = ratio.gt(rules.max_up_jump)
    broke = is_gap | is_jump
    segment = broke.groupby(frame["symbol"], sort=False, observed=True).cumsum().astype("int64")

    names = [segment_symbol(str(s), int(k)) for s, k in zip(frame["symbol"], segment, strict=True)]
    out = frame.assign(symbol=pd.Series(names, index=frame.index, dtype=frame["symbol"].dtype))

    rows = frame.loc[broke, ["symbol", "timestamp"]].assign(
        segment_symbol=[names[i] for i in np.flatnonzero(broke.to_numpy())],
        gap_days=gap[broke].to_numpy(),
        price_ratio=ratio[broke].to_numpy(),
        reason=np.where(is_gap[broke] & is_jump[broke], REASON_BOTH, np.where(is_gap[broke], REASON_GAP, REASON_JUMP)),
    ).rename(columns={"timestamp": "break_day"})
    report = rows[list(REPORT_SCHEMA)].astype(REPORT_SCHEMA).reset_index(drop=True)
    return out, report
