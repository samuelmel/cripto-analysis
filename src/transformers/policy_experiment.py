"""Cenário de pesquisa: baselines, candidatas e políticas por regime sob as MESMAS condições (Fase 5).

Puro (CLAUDE.md §1). Reaproveita o motor de pesos de `selection_backtest` (`run_weighted`, `baseline_targets`,
`market_returns`): mesmos dados, universo elegível, calendário de rebalanceamento, custos por moeda, faixa de
tolerância, capital inicial em caixa e exposição máxima de 100%. Execução: decisão no fechamento de `d`, retorno de
`d + 1` (convenção existente); `lag_days` atrasa a execução em dias inteiros.

Nada é importado pela produção.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from .. import config
from .regime_policy import (
    CASH,
    FIXED_POLICIES,
    LEARNABLE,
    POLICY_LEARNED,
    count_switches,
    fixed_chooser,
    learned_chooser,
    policy_targets,
    random_dropout,
)
from .backtest_engine import WeightedRun
from .selection import SelectionRules, regime_series
from .selection_backtest import (
    STRATEGY_BTC,
    STRATEGY_HOLD_ALL,
    STRATEGY_MOMENTUM,
    STRATEGY_SELECTION,
    STRATEGY_SMA200,
    baseline_targets,
    market_returns,
    rebalance_days,
    run_weighted,
    selection_targets,
)

BASELINES: tuple[str, ...] = (STRATEGY_HOLD_ALL, STRATEGY_SMA200, STRATEGY_MOMENTUM, STRATEGY_BTC)


@dataclass(frozen=True)
class Scenario:
    """Uma variante declarada do protocolo (uma perturbação por vez em torno da base)."""

    name: str = "base"
    cost_scale: float = 1.0
    lag_days: int = 0
    every: int = config.SELECTION_REBALANCE_DAYS
    universe: tuple[str, ...] | None = None  # None = todas as moedas da base
    regime_dropout: float = 0.0              # fração de dias com regime INDISPONIVEL (falha de dados simulada)
    band: float = config.REBALANCE_BAND      # faixa de tolerância do motor; 0 = alvo exato (exposição bruta <= 100%)

    def __post_init__(self) -> None:
        if self.cost_scale < 0 or self.lag_days < 0 or self.every < 1 or not 0.0 <= self.regime_dropout < 1.0 or self.band < 0:
            raise ValueError("cenário inválido: custo >= 0, atraso >= 0, every >= 1, 0 <= dropout < 1")


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    runs: Mapping[str, WeightedRun]         # baselines, políticas e (opcional) a seleção de produção
    decisions: pd.DataFrame                 # DECISION_SCHEMA, todas as políticas
    mappings: pd.DataFrame                  # MAPPING_SCHEMA (P5)
    switches: Mapping[str, int]             # trocas de estratégia por política
    eligible_symbols: tuple[str, ...] = field(default_factory=tuple)


def _shift(targets: pd.DataFrame, lag_days: int) -> pd.DataFrame:
    if lag_days == 0:
        return targets
    return targets.set_axis(targets.index + pd.Timedelta(days=lag_days), axis=0)


def run_scenario(
    features: pd.DataFrame,
    regime: pd.DataFrame,
    scenario: Scenario,
    start: pd.Timestamp,
    end: pd.Timestamp,
    seed: int,
    *,
    include_selection: bool = False,
) -> ScenarioResult:
    """Roda baselines e políticas em [start, end]. As candidatas também rodam desde o início da base, só para o
    treino de P5 (que usa retornos anteriores ao ano de cada decisão)."""
    if scenario.universe is not None:
        features = features[features.index.get_level_values("symbol").isin(scenario.universe)]
    days = [pd.Timestamp(d) for d in rebalance_days(features, scenario.every)]
    returns, cost = market_returns(features)
    cost = cost * scenario.cost_scale
    base = baseline_targets(features, config.REGIME_SYMBOL, days, config.MAX_CANDIDATES)
    candidates = {s: base[s] for s in (STRATEGY_HOLD_ALL, STRATEGY_SMA200, STRATEGY_MOMENTUM)}
    candidates[CASH] = pd.DataFrame(0.0, index=base[STRATEGY_BTC].index, columns=base[STRATEGY_BTC].columns)
    table = random_dropout(regime, scenario.regime_dropout, seed)

    first, last = days[0], returns.index.max()
    full = {s: run_weighted(_shift(candidates[s], scenario.lag_days), returns, cost, first, last, scenario.band).daily for s in LEARNABLE}
    trend = pd.Series(table["trend_regime"].to_numpy(dtype=object), index=pd.DatetimeIndex(table["timestamp"]))
    choose_learned, mappings = learned_chooser(pd.DataFrame(full), trend.shift(1, freq="D"))

    runs: dict[str, WeightedRun] = {}
    decisions: list[pd.DataFrame] = []
    switches: dict[str, int] = {}
    choosers = {name: fixed_chooser(policy) for name, policy in FIXED_POLICIES.items()}
    choosers[POLICY_LEARNED] = choose_learned
    for name, chooser in choosers.items():
        weights, made = policy_targets(chooser, name, candidates, table, days)
        runs[name] = run_weighted(_shift(weights, scenario.lag_days), returns, cost, start, end, scenario.band)
        decisions.append(made)
        switches[name] = count_switches(made)
    for name in BASELINES:
        runs[name] = run_weighted(_shift(base[name], scenario.lag_days), returns, cost, start, end, scenario.band)
    if include_selection:
        legacy = regime_series(features)
        sel = selection_targets(features, legacy, days, config.BUDGET_BRL, SelectionRules())
        runs[STRATEGY_SELECTION] = run_weighted(_shift(sel.variable, scenario.lag_days), returns, cost, start, end, scenario.band)
    eligible = tuple(str(s) for s in features.index.get_level_values("symbol").unique())
    return ScenarioResult(scenario, runs, pd.concat(decisions, ignore_index=True), mappings(), switches, eligible)
