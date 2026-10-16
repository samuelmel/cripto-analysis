"""Contrato da recomendação do dia: junta sinais, seleção e alocação num formato único para painel e Telegram.

Puro (CLAUDE.md §1). A recomendação é calculada uma vez (pipeline) e publicada em dois arquivos da MESMA execução,
ligados por `run_ts`:

    daily_signals.parquet    uma linha por moeda (SIGNALS_SCHEMA): o sinal SMA 200 de antes + score, componentes,
                             classificação, motivos, riscos, bloqueios e aporte sugerido
    recommendation.parquet   uma linha (RECOMMENDATION_SCHEMA): orçamento, mercado, total sugerido, saldo não
                             alocado, decisão, avisos, evidência histórica e estado dos dados

`validate_recommendation` confere as invariantes antes de publicar (soma <= orçamento, aporte só em moeda
selecionada e com dado confiável); qualquer violação impede a publicação.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd

from .allocation import ALLOCATION_SCHEMA, AllocationSummary
from .daily_alerts import DAILY_SCHEMA
from .selection import OPP_AVOID, SELECTION_SCHEMA

BUDGET_SIMULATION = "SIMULACAO"
DATA_OK = "OK"
DATA_PARTIAL = "PARCIAL"
DATA_UNAVAILABLE = "INDISPONIVEL"

SIGNALS_SCHEMA: dict[str, str] = {
    **DAILY_SCHEMA,
    **{k: v for k, v in SELECTION_SCHEMA.items() if k != "symbol"},
    **{k: v for k, v in ALLOCATION_SCHEMA.items() if k != "symbol"},
    "run_ts": "datetime64[ns, UTC]",
}

RECOMMENDATION_SCHEMA: dict[str, str] = {
    "run_ts": "datetime64[ns, UTC]",       # data e hora da análise
    "data_day": "datetime64[ns, UTC]",     # último candle diário fechado usado (abre às 00:00 UTC desse dia)
    "budget_brl": "float64",
    "budget_mode": "string",               # SIMULACAO: sem integração com saldo real
    "regime": "string",                    # FAVORAVEL / NEUTRO / DEFENSIVO / INDISPONIVEL
    "regime_filter": "string",             # bloquear / reduzir / desligado (config.REGIME_FILTER)
    "regime_close": "float64",             # fechamento do BTC no dia
    "regime_sma_200": "float64",
    "total_brl": "float64",
    "unallocated_brl": "float64",
    "theoretical_total_brl": "float64",
    "capped_by_budget": "bool",
    "decision": "string",                  # NAO_INVESTIR / APORTE_PEQUENO / APORTE_PARCIAL / APORTE_AMPLO
    "n_analyzed": "Int64",
    "n_candidates": "Int64",
    "n_selected": "Int64",
    "n_funded": "Int64",
    "notes": "object",                     # lista de str: limites do orçamento, aportes impraticáveis
    "excluded": "object",                  # lista de str: moedas fora da análise e por quê
    "evidence": "string",                  # o que o backtest do período de teste mostrou (histórico, não prospectivo)
    "data_status": "string",               # OK / PARCIAL / INDISPONIVEL
    "data_notes": "object",                # lista de str: limitações dos dados nesta execução
}


def build_recommendation(
    signals: pd.DataFrame,
    assessed: pd.DataFrame,
    allocation: pd.DataFrame,
    summary: AllocationSummary,
    *,
    run_ts: pd.Timestamp,
    regime: str,
    regime_filter: str,
    regime_symbol: str,
    excluded: Sequence[str],
    evidence: str,
    data_notes: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(daily_signals no SIGNALS_SCHEMA, recommendation com uma linha no RECOMMENDATION_SCHEMA)."""
    sel = assessed.merge(allocation, on="symbol", how="left", validate="one_to_one")
    out = signals.merge(sel.astype({"symbol": "string"}), on="symbol", how="left", validate="one_to_one")
    missing = out["opportunity"].isna()
    if missing.any():  # moeda sem indicadores no dia: nunca recomendada
        out.loc[missing, "opportunity"] = OPP_AVOID
        out.loc[missing, "selected"] = False
        for col in ("conditions", "reasons", "risks"):
            out.loc[missing, col] = pd.Series([[] for _ in range(int(missing.sum()))], index=out.index[missing], dtype="object")
        out.loc[missing, "blockers"] = pd.Series([["sem indicadores para o dia analisado"] for _ in range(int(missing.sum()))],
                                                 index=out.index[missing], dtype="object")
        for col in ("target_fraction", "theoretical_brl", "allocation_brl"):
            out.loc[missing, col] = 0.0
    out["run_ts"] = run_ts
    out = out[list(SIGNALS_SCHEMA)].astype(SIGNALS_SCHEMA)

    btc = signals[signals["symbol"].eq(regime_symbol)]
    status = DATA_UNAVAILABLE if regime == "INDISPONIVEL" else DATA_PARTIAL if data_notes else DATA_OK
    rec = pd.DataFrame(
        [
            {
                "run_ts": run_ts,
                "data_day": pd.Timestamp(signals["timestamp"].max()) if not signals.empty else pd.NaT,
                "budget_brl": summary.budget_brl,
                "budget_mode": BUDGET_SIMULATION,
                "regime": regime,
                "regime_filter": regime_filter,
                "regime_close": float(btc["close"].iloc[0]) if not btc.empty else math.nan,
                "regime_sma_200": float(btc["sma_200"].iloc[0]) if not btc.empty and pd.notna(btc["sma_200"].iloc[0]) else math.nan,
                "total_brl": summary.total_brl,
                "unallocated_brl": summary.unallocated_brl,
                "theoretical_total_brl": summary.theoretical_total_brl,
                "capped_by_budget": summary.capped_by_budget,
                "decision": summary.decision,
                "n_analyzed": len(out),
                "n_candidates": int(out["opportunity"].isin(["BOA_RELATIVA", "MODERADA"]).sum()),
                "n_selected": int(out["selected"].sum()),
                "n_funded": int(out["allocation_brl"].gt(0).sum()),
                "notes": list(summary.notes),
                "excluded": list(excluded),
                "evidence": evidence,
                "data_status": status,
                "data_notes": list(data_notes),
            }
        ]
    )
    return out, rec[list(RECOMMENDATION_SCHEMA)].astype(RECOMMENDATION_SCHEMA)


def validate_recommendation(signals: pd.DataFrame, rec: pd.DataFrame) -> list[str]:
    """Invariantes do contrato. Lista vazia = pode publicar."""
    problems: list[str] = []
    if len(rec) != 1:
        return [f"recommendation deve ter 1 linha (tem {len(rec)})"]
    r = rec.iloc[0]
    budget = float(r["budget_brl"])
    amounts = signals["allocation_brl"].astype("float64")
    total = float(amounts.sum())
    if not amounts.map(math.isfinite).all() or (amounts < 0).any():
        problems.append("aporte negativo ou inválido")
    if total > budget + 1e-6:
        problems.append(f"soma dos aportes ({total:.2f}) passa do orçamento ({budget:.2f})")
    if not math.isclose(total, float(r["total_brl"]), abs_tol=1e-6):
        problems.append("total do resumo difere da soma por moeda")
    if not math.isclose(float(r["unallocated_brl"]), budget - total, abs_tol=1e-6):
        problems.append("saldo não alocado difere de orçamento − total")
    funded = signals[amounts.gt(0)]
    if (~funded["selected"].astype(bool)).any():
        problems.append("aporte em moeda não selecionada")
    if funded["stage"].eq("INDISPONÍVEL").any():
        problems.append("aporte em moeda sem dado confiável")
    if signals["run_ts"].nunique() != 1 or pd.Timestamp(signals["run_ts"].iloc[0]) != pd.Timestamp(r["run_ts"]):
        problems.append("run_ts diferente entre daily_signals e recommendation")
    return problems
