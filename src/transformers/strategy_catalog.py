"""Catálogo das estratégias e políticas que existem no código, com o estado da evidência.

Puro (CLAUDE.md §1): só dados. Serve para não confundir nomes de relatórios com o que está implementado, e para
registrar, num lugar só, que **nenhuma estratégia foi confirmada como robusta** (conclusão histórica das Fases 2 a 5;
os resultados são exploratórios, sem período prospectivo). Um teste confere que todo nome de estratégia usado pelos
motores aparece aqui. Atualizar a evidência exige uma análise reproduzível e metodologicamente válida, registrada em
`data/research/experiments.parquet`, e não a simples edição deste arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass

from .regime_policy import CASH, POLICY_HOLD_UP, POLICY_LEARNED, POLICY_MOMENTUM_UP, POLICY_PRIMARY, POLICY_VOL_FILTERED
from .selection_backtest import (
    STRATEGY_BTC,
    STRATEGY_HOLD_ALL,
    STRATEGY_MOMENTUM,
    STRATEGY_SELECTION,
    STRATEGY_SELECTION_EQUAL,
    STRATEGY_SMA200,
)
from .trade_simulator import STRATEGY_HOLD, STRATEGY_PANIC, STRATEGY_TREND

assert STRATEGY_HOLD == STRATEGY_HOLD_ALL  # mesmo nome nos dois motores (ver o catálogo)

KIND_PRODUCTION = "PRODUCAO"      # alimenta a recomendação ou o painel
KIND_BASELINE = "BASELINE"        # referência simples de comparação
KIND_RESEARCH = "PESQUISA"        # só em research/, sem efeito na produção
KIND_LEGACY = "LEGADO"            # congelada, só para comparação histórica
KINDS: tuple[str, ...] = (KIND_PRODUCTION, KIND_BASELINE, KIND_RESEARCH, KIND_LEGACY)

NOT_CONFIRMED = "NAO_CONFIRMADA_ROBUSTA"


@dataclass(frozen=True)
class StrategyEntry:
    name: str
    kind: str
    engine: str          # onde é simulada
    description: str
    evidence: str = NOT_CONFIRMED

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"tipo desconhecido: {self.kind!r}")


ENGINE_PORTFOLIO = "trade_simulator.run_portfolio (posição 0/1 diária, só taxa)"
ENGINE_WEIGHTS = "selection_backtest.run_weighted (pesos semanais, taxa + spread + slippage)"

CATALOG: tuple[StrategyEntry, ...] = (
    StrategyEntry(STRATEGY_TREND, KIND_PRODUCTION, ENGINE_PORTFOLIO, "Regra principal SMA 200 em BTC e ETH, com filtro do BTC e stop opcional"),
    StrategyEntry(STRATEGY_PANIC, KIND_LEGACY, ENGINE_PORTFOLIO, "Regra antiga de comprar no pânico, congelada (perdeu dinheiro no backtest)"),
    StrategyEntry(STRATEGY_SELECTION, KIND_PRODUCTION, ENGINE_WEIGHTS, "Seleção de oportunidades com aporte por volatilidade (recomendação diária)"),
    StrategyEntry(STRATEGY_SELECTION_EQUAL, KIND_BASELINE, ENGINE_WEIGHTS, "A mesma seleção com peso igual: isola o efeito do dimensionamento"),
    # Atenção: o MESMO nome existe nos dois motores (`trade_simulator.STRATEGY_HOLD` e `selection_backtest.STRATEGY_HOLD_ALL`)
    # com simulações diferentes: posição 0/1 diária com só taxa, ou pesos semanais com spread e slippage. Os resultados
    # dos dois não são comparáveis entre si.
    StrategyEntry(STRATEGY_HOLD_ALL, KIND_BASELINE, f"{ENGINE_PORTFOLIO} e {ENGINE_WEIGHTS}", "Comprar e segurar, peso igual entre as moedas elegíveis (motores diferentes, mesmo nome)"),
    StrategyEntry(STRATEGY_SMA200, KIND_BASELINE, ENGINE_WEIGHTS, "Moedas acima da SMA 200 com o BTC também acima, peso igual"),
    StrategyEntry(STRATEGY_MOMENTUM, KIND_BASELINE, ENGINE_WEIGHTS, "As 3 de maior retorno em 90 dias, peso igual"),
    StrategyEntry(STRATEGY_BTC, KIND_BASELINE, ENGINE_WEIGHTS, "Só Bitcoin, comprado e segurado"),
    StrategyEntry(CASH, KIND_RESEARCH, ENGINE_WEIGHTS, "Nenhuma posição (opção das políticas por regime)"),
    StrategyEntry(POLICY_PRIMARY, KIND_RESEARCH, ENGINE_WEIGHTS, "Tendência SMA 200 só no regime ALTA; caixa nos demais (primária da Fase 5)"),
    StrategyEntry(POLICY_MOMENTUM_UP, KIND_RESEARCH, ENGINE_WEIGHTS, "Momento em ALTA, tendência em MISTO, caixa nos demais"),
    StrategyEntry(POLICY_VOL_FILTERED, KIND_RESEARCH, ENGINE_WEIGHTS, "Tendência em ALTA com volatilidade normal; caixa nos demais"),
    StrategyEntry(POLICY_HOLD_UP, KIND_RESEARCH, ENGINE_WEIGHTS, "Comprar e segurar em ALTA; caixa nos demais"),
    StrategyEntry(POLICY_LEARNED, KIND_RESEARCH, ENGINE_WEIGHTS, "Melhor candidata por regime, aprendida só com o passado a cada ano"),
)

BY_NAME: dict[str, StrategyEntry] = {e.name: e for e in CATALOG}
if len(BY_NAME) != len(CATALOG):
    raise ValueError("nomes repetidos no catálogo de estratégias")


def confirmed_robust() -> tuple[str, ...]:
    """Estratégias com evidência confirmada como robusta. Vazio hoje, de propósito."""
    return tuple(e.name for e in CATALOG if e.evidence != NOT_CONFIRMED)
