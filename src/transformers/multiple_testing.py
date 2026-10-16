"""Correção para comparações múltiplas: Holm-Bonferroni sobre uma família de hipóteses declarada antes.

Puro (CLAUDE.md §1).

Holm (1979) controla o erro familiar (FWER: chance de rejeitar ao menos uma hipótese nula verdadeira) em nível
`alpha` sob QUALQUER dependência entre os testes. É conservador quando os testes são positivamente correlacionados
(estratégias parecidas sobre o mesmo mercado), por isso a validação também publica o ajuste pelo máximo da
estatística do bootstrap (`bootstrap.max_stat_pvalues`), que usa essa correlação.

Família. Os membros e o tamanho m são fixados ANTES dos resultados (registro de experimentos). Uma hipótese que não
pôde ser testada (dado ausente, amostra insuficiente, teste inválido) continua na família com p = 1: não rejeita
e não diminui m. Tirá-la depois de ver os dados seria escolher a família pelo resultado.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

HOLM_SCHEMA: dict[str, str] = {
    "hypothesis": "string",
    "p_value": "float64",       # p bruto (NaN = não testada)
    "p_used": "float64",        # o que entrou no ajuste (1 quando não testada)
    "p_holm": "float64",
    "reject": "bool",
    "untested": "bool",
    "family_size": "Int64",
    "alpha": "float64",
}


def holm(pvalues: Mapping[str, float], alpha: float = 0.05) -> pd.DataFrame:
    """p-valores ajustados por Holm e decisão de rejeição (HOLM_SCHEMA), na ordem de entrada.

    Ajustado da i-ésima menor: max_{j<=i} min(1, (m − j + 1)·p_(j)). Rejeita quando ajustado <= alpha (equivale ao
    procedimento sequencial: para no primeiro p_(i) > alpha / (m − i + 1)).
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha em (0, 1)")
    names = list(pvalues)
    raw = np.array([float(pvalues[k]) for k in names], dtype="float64")
    for p in raw:
        if math.isfinite(p) and not 0.0 <= p <= 1.0:
            raise ValueError("p-valor fora de [0, 1]")
    untested = ~np.isfinite(raw)
    used = np.where(untested, 1.0, raw)
    m = len(names)
    order = np.argsort(used, kind="mergesort")
    adjusted_sorted = np.minimum(1.0, (m - np.arange(m)) * used[order])
    adjusted_sorted = np.maximum.accumulate(adjusted_sorted) if m else adjusted_sorted
    adjusted = np.empty(m)
    adjusted[order] = adjusted_sorted
    out = pd.DataFrame({
        "hypothesis": names,
        "p_value": raw,
        "p_used": used,
        "p_holm": adjusted,
        "reject": (adjusted <= alpha) & ~untested,
        "untested": untested,
        "family_size": m,
        "alpha": alpha,
    })
    return out.astype(HOLM_SCHEMA)
