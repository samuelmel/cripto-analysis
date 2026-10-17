"""Modelo de custos de execução: taxa, meia-largura do spread e slippage, separados e configuráveis.

Puro (CLAUDE.md §1). Única fonte das hipóteses de custo: a camada de seleção (custo estimado de cada moeda, que
decide se um aporte é viável) e o motor de backtest (`backtest_engine.py`) usam as mesmas funções e os mesmos
números de `config.py`, então a recomendação e a avaliação histórica cobram o mesmo custo.

Por lado (compra ou venda), sobre o preço de referência p:
    preço de compra executado = p × (1 + meio-spread + slippage)
    preço de venda executado  = p × (1 − meio-spread − slippage)
    taxa da corretora         = notional executado × fee_rate, paga em caixa
O meio-spread é estimado pela faixa de volume médio de 30 dias (`config.SPREAD_TIERS`); sem volume medido vale a
faixa mais cara. São HIPÓTESES conservadoras (as fontes não têm livro de ofertas), não medidas.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config


@dataclass(frozen=True)
class CostModel:
    fee_rate: float = config.FEE_PER_SIDE
    slippage: float = config.SLIPPAGE
    spread_tiers: tuple[tuple[float, float], ...] = config.SPREAD_TIERS

    def __post_init__(self) -> None:
        if not (0 <= self.fee_rate < 0.1 and 0 <= self.slippage < 0.1):
            raise ValueError("fee_rate e slippage precisam estar em [0, 0,1)")
        if not self.spread_tiers or any(h < 0 or h >= 0.1 for _, h in self.spread_tiers):
            raise ValueError("spread_tiers precisa de faixas com meio-spread em [0, 0,1)")

    @property
    def worst_half_spread(self) -> float:
        return max(half for _, half in self.spread_tiers)


def half_spread(avg_volume: pd.DataFrame, model: CostModel = CostModel()) -> pd.DataFrame:
    """Meia-largura do spread estimada pela faixa de volume médio (fração do preço); sem volume, a faixa mais cara."""
    spread = pd.DataFrame(np.nan, index=avg_volume.index, columns=avg_volume.columns)
    for floor, half in sorted(model.spread_tiers, key=lambda t: t[0]):  # da faixa mais baixa para a mais alta
        spread = spread.mask(avg_volume.ge(floor), half)
    return spread.fillna(model.worst_half_spread)


def cost_per_side(avg_volume: pd.DataFrame, model: CostModel = CostModel()) -> pd.DataFrame:
    """Custo total estimado por lado (taxa + meio-spread + slippage), fração do notional."""
    return half_spread(avg_volume, model) + model.fee_rate + model.slippage
