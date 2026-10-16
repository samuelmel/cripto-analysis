"""Quanto aportar: converte a seleção do dia em valores em reais, dentro de um orçamento total.

Puro (CLAUDE.md §1). Responde três perguntas: vale a pena aportar nesta análise? quanto em cada moeda?
quanto do orçamento fica sem investir?

Metodologia (todos os números em config.py, documentados no README):
    1. Só moedas `selected` (BOA_RELATIVA ou MODERADA, até MAX_CANDIDATES) recebem valor; as primeiras
       MAX_POSITIONS, na ordem do ranking.
    2. Fração-alvo teórica = min(MAX_ALLOCATION_PCT, TARGET_VOL_PER_POSITION / volatilidade anual da moeda)
       × CONVICTION da classificação (× REGIME_REDUCE_FACTOR com REGIME_FILTER = "reduzir" e mercado defensivo).
       Dimensionamento por volatilidade: a moeda que oscila o dobro recebe a metade, e cada posição contribui com
       um risco parecido. Não usa perdas anteriores para aumentar aporte (sem martingale).
    3. Alocação teórica = orçamento × fração. A soma pode passar do orçamento (várias candidatas fortes): nesse
       caso todas são reduzidas na mesma proporção e o resumo informa a exposição-alvo teórica, sem nunca
       recomendar além do orçamento.
    4. Arredondamento PARA BAIXO em múltiplos de ROUND_TO_BRL; abaixo de MIN_ORDER_BRL vira zero; custo
       estimado (FIXED_COST_BRL + taxa, spread e slippage de ida e volta) acima de MAX_COST_PCT vira zero.
       O motivo de cada zero aparece em `allocation_note`.
    5. Invariante verificada: 0 <= soma dos aportes <= orçamento. Violação levanta ValueError (nunca publica).

Os valores são estimativas de dimensionamento do modelo, não garantia de retorno.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config
from .selection import FILTER_REDUCE, REGIME_DEFENSIVE, as_float

ALLOCATION_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "target_fraction": "float64",  # fração-alvo do orçamento antes do limite do orçamento
    "theoretical_brl": "float64",  # alocação teórica (pode somar mais que o orçamento)
    "allocation_brl": "float64",   # sugestão prática, já arredondada e limitada
    "allocation_note": "string",   # por que o valor prático difere do teórico (ou nulo)
}

DECISION_NONE = "NAO_INVESTIR"
DECISION_SMALL = "APORTE_PEQUENO"
DECISION_PARTIAL = "APORTE_PARCIAL"
DECISION_FULL = "APORTE_AMPLO"


@dataclass(frozen=True)
class AllocationRules:
    max_positions: int = config.MAX_POSITIONS
    max_allocation_pct: float = config.MAX_ALLOCATION_PCT
    target_vol: float = config.TARGET_VOL_PER_POSITION
    conviction: Mapping[str, float] = field(default_factory=lambda: dict(config.CONVICTION))
    regime_filter: str = config.REGIME_FILTER
    regime_reduce_factor: float = config.REGIME_REDUCE_FACTOR
    round_to: float = config.ROUND_TO_BRL
    min_order: float = config.MIN_ORDER_BRL
    fixed_cost: float = config.FIXED_COST_BRL
    max_cost_pct: float = config.MAX_COST_PCT

    def __post_init__(self) -> None:
        if self.round_to <= 0 or self.min_order < 0 or self.fixed_cost < 0:
            raise ValueError("ROUND_TO_BRL precisa ser > 0; MIN_ORDER_BRL e FIXED_COST_BRL, >= 0")
        if not 0 < self.max_allocation_pct <= 1 or self.target_vol <= 0 or self.max_positions < 0:
            raise ValueError("MAX_ALLOCATION_PCT em (0, 1], TARGET_VOL_PER_POSITION > 0 e MAX_POSITIONS >= 0")


@dataclass(frozen=True)
class AllocationSummary:
    budget_brl: float
    total_brl: float
    unallocated_brl: float
    theoretical_total_brl: float
    capped_by_budget: bool
    decision: str
    notes: tuple[str, ...]


def _brl(x: float) -> str:
    whole = math.isclose(x, round(x))
    text = f"{x:,.{0 if whole else 2}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def _floor_to(x: float, step: float) -> float:
    return math.floor(x / step + 1e-9) * step


def allocate(
    selection: pd.DataFrame,
    budget: float,
    regime: str,
    rules: AllocationRules = AllocationRules(),
) -> tuple[pd.DataFrame, AllocationSummary]:
    """Aporte sugerido por moeda (ALLOCATION_SCHEMA, mesma ordem de `selection`) e o resumo do orçamento.

    `selection`: saída de `selection.assess` (usa symbol, opportunity, selected, vol_90d_pct, est_cost_pct).
    """
    if not math.isfinite(budget) or budget < 0:
        raise ValueError(f"orçamento inválido: {budget!r}")
    notes: list[str] = []
    out = pd.DataFrame(
        {
            "symbol": selection["symbol"].astype("string"),
            "target_fraction": 0.0,
            "theoretical_brl": 0.0,
            "allocation_brl": 0.0,
            "allocation_note": pd.Series(pd.NA, index=selection.index, dtype="string"),
        },
        index=selection.index,
    )
    chosen = selection.index[selection["selected"].fillna(False).astype(bool)]
    regime_factor = rules.regime_reduce_factor if (regime == REGIME_DEFENSIVE and rules.regime_filter == FILTER_REDUCE) else 1.0
    funded: list[object] = []
    for i in chosen:
        vol = as_float(selection.at[i, "vol_90d_pct"]) / 100.0
        conviction = float(rules.conviction.get(str(selection.at[i, "opportunity"]), 0.0))
        if not (math.isfinite(vol) and vol > 0) or conviction <= 0:
            out.at[i, "allocation_note"] = "sem volatilidade medida: não dá para dimensionar"
            continue
        fraction = min(rules.max_allocation_pct, rules.target_vol / vol) * conviction * regime_factor
        out.at[i, "target_fraction"] = fraction
        out.at[i, "theoretical_brl"] = budget * fraction
        if len(funded) >= rules.max_positions:
            out.at[i, "allocation_note"] = f"limite de {rules.max_positions} posições simultâneas"
            continue
        funded.append(i)

    theoretical = float(out["theoretical_brl"][out.index.isin(funded)].sum())
    theoretical_all = float(out["theoretical_brl"].sum())
    scale = min(1.0, budget / theoretical) if theoretical > 0 else 0.0
    capped = theoretical > budget + 1e-9
    if capped:
        notes.append(
            f"O modelo teria uma exposição-alvo de {_brl(round(theoretical, 2))}; a sugestão fica limitada ao orçamento "
            f"de {_brl(budget)} (todas as moedas reduzidas na mesma proporção)."
        )
    if regime_factor < 1.0:
        notes.append(f"Mercado defensivo: alvos reduzidos a {int(regime_factor * 100)}% pela regra de risco.")

    for i in funded:
        raw = as_float(out.at[i, "theoretical_brl"]) * scale
        amount = _floor_to(raw, rules.round_to)
        cost = as_float(selection.at[i, "est_cost_pct"]) / 100.0
        cost_pct = cost if math.isfinite(cost) else 0.0
        if amount < rules.min_order or amount <= 0:
            out.at[i, "allocation_note"] = (
                f"aporte de {_brl(round(raw, 2))} fica abaixo da ordem mínima de {_brl(rules.min_order)}: impraticável"
            )
            amount = 0.0
        elif rules.fixed_cost / amount + cost_pct > rules.max_cost_pct:
            total = rules.fixed_cost / amount + cost_pct
            out.at[i, "allocation_note"] = (
                f"custo estimado de {total * 100:.1f}% do aporte (máximo {rules.max_cost_pct * 100:.0f}%): economicamente inviável"
            ).replace(".", ",")
            amount = 0.0
        elif amount < raw - 1e-9:
            out.at[i, "allocation_note"] = f"arredondado para baixo em múltiplos de {_brl(rules.round_to)}"
        out.at[i, "allocation_brl"] = amount

    total = float(out["allocation_brl"].sum())
    if total > budget + 1e-9 or total < 0 or not np.isfinite(out["allocation_brl"]).all():
        raise ValueError(f"alocação de {total} fora do orçamento de {budget}")  # nunca deve acontecer: invariante
    if budget < rules.min_order and len(chosen) > 0:
        notes.append(f"Orçamento de {_brl(budget)} abaixo da ordem mínima de {_brl(rules.min_order)}: não há aporte executável.")
    elif len(chosen) > 0 and total == 0:
        notes.append("Havia candidatas, mas nenhum aporte é executável com os limites mínimos e custos configurados.")

    share = total / budget if budget > 0 else 0.0
    decision = (
        DECISION_NONE if total == 0
        else DECISION_SMALL if share <= 0.30
        else DECISION_PARTIAL if share <= 0.60
        else DECISION_FULL
    )
    summary = AllocationSummary(
        budget_brl=budget,
        total_brl=total,
        unallocated_brl=budget - total,
        theoretical_total_brl=theoretical_all,
        capped_by_budget=capped,
        decision=decision,
        notes=tuple(notes),
    )
    return out[list(ALLOCATION_SCHEMA)].astype(ALLOCATION_SCHEMA), summary

