"""Motor único de backtest de carteira por pesos-alvo (CLAUDE.md §1: puro, sem I/O).

Todo backtest de carteira do projeto passa por `simulate_weights`: `run_weighted` (seleção, pesquisa) e
`run_portfolio` (posições 0/1 da regra de tendência) são adaptadores finos sobre ele. Assim execução, custos e
exposição têm uma só definição.

Convenções:
    decisão      o peso-alvo é decidido no FECHAMENTO do dia `d` (só com dados até `d`).
    execução     a ordem é executada no fechamento de `d + execution_lag` dias de negociação (padrão 1: o fechamento
                 SEGUINTE ao sinal). O peso passa a render a partir do retorno do dia seguinte à execução.
                 `execution_lag=0` reproduz a versão antiga (executa no mesmo fechamento do sinal) e existe só para
                 comparação e testes.
    deriva       entre rebalanceamentos os pesos flutuam com os preços.
    faixa        moeda mantida (peso atual e alvo > 0) só é reajustada se |alvo − atual| > `band`.
    custo        |mudança de peso| × custo por lado da moeda, cobrado no dia em que a nova posição começa a render.
                 O custo por lado (taxa + spread + slippage) vem de `config.py` via quem chama.
    sem preço    moeda carregada sem preço no dia: retorno 0 (preço parado), contado em `stale_weight_days`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config

ENGINE_VERSION = "engine-3"
"""1: faixa sem limite de exposição. 2: guarda de exposição. 3 (motor único): execução no fechamento seguinte ao
sinal (`execution_lag=1`) e `run_portfolio` sobre o mesmo núcleo. Entra na configuração dos experimentos."""

EXECUTION_LAG = 1
"""Dias de negociação entre o fechamento do sinal e o fechamento da execução."""


@dataclass(frozen=True)
class WeightedRun:
    daily: pd.Series        # retorno diário da carteira, líquido de custos
    exposure: pd.Series     # soma dos pesos carregados em cada dia
    turnover: float         # soma de |mudança de peso| nos rebalanceamentos
    cost: float             # custos totais, fração do capital
    n_trades: int
    stale_weight_days: float = 0.0  # Σ peso × dias em que a moeda carregada não tinha preço (retorno tratado como 0)
    cost_daily: pd.Series | None = None  # custo cobrado em cada dia, fração do capital


def _execution_plan(
    targets: pd.DataFrame, cols: list[str], index: pd.DatetimeIndex, lag: int
) -> dict[pd.Timestamp, np.ndarray]:
    """Dia de execução -> pesos-alvo. Alvo decidido em `d` executa `lag` dias de negociação depois (em `index`)."""
    t = targets.reindex(columns=cols).fillna(0.0)
    plan: dict[pd.Timestamp, np.ndarray] = {}
    for day, row in zip(t.index, t.to_numpy(dtype="float64"), strict=True):
        pos = int(index.searchsorted(pd.Timestamp(day)))
        if pos >= len(index) or index[pos] != pd.Timestamp(day):
            continue  # dia sem linha de retorno: o alvo não pode ser decidido nem executado
        if pos + lag < len(index):
            plan[pd.Timestamp(index[pos + lag])] = row
    return plan


def simulate_weights(
    targets: pd.DataFrame,
    returns: pd.DataFrame,
    cost_per_side: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    band: float = config.REBALANCE_BAND,
    guard_exposure: bool = True,
    execution_lag: int = EXECUTION_LAG,
) -> WeightedRun:
    """Simula pesos-alvo (`targets`: linhas = dias de decisão, valores = fração do capital) em [start, end].

    `guard_exposure` (padrão): a faixa não pode produzir exposição total acima da exposição-alvo (alavancagem
    implícita) nem mais de `band` abaixo dela (caixa parado); nesses casos o rebalanceamento vai direto aos alvos.
    `False` reproduz o motor da versão 1, só para comparação.
    """
    if execution_lag < 0:
        raise ValueError("execution_lag precisa ser >= 0")
    days = returns.loc[start:end].index
    cols = list(returns.columns)
    if len(days) == 0:
        empty = pd.Series(dtype="float64")
        return WeightedRun(empty, empty, 0.0, 0.0, 0, 0.0, empty)
    raw = returns.reindex(index=days, columns=cols).to_numpy(dtype="float64")
    missing = np.isnan(raw)
    r = np.where(missing, 0.0, raw)
    stale = 0.0
    c = cost_per_side.reindex(index=days, columns=cols).ffill().fillna(0.0).to_numpy(dtype="float64")
    plan = _execution_plan(targets, cols, pd.DatetimeIndex(returns.index), execution_lag)

    w = np.zeros(len(cols))
    pending = 0.0
    out = np.zeros(len(days))
    exposure = np.zeros(len(days))
    paid = np.zeros(len(days))
    turnover = cost = 0.0
    trades = 0
    for i, day in enumerate(days):
        gross = float(w @ r[i])
        stale += float(w @ missing[i])
        out[i] = (1.0 - pending) * (1.0 + gross) - 1.0
        exposure[i] = float(w.sum())
        paid[i] = pending
        cost += pending
        pending = 0.0
        growth = 1.0 + gross
        if growth > 0:
            w = w * (1.0 + r[i]) / growth
        target = plan.get(pd.Timestamp(day))
        if target is not None:
            keep = (w > 1e-12) & (target > 1e-12) & (np.abs(target - w) <= band)
            goal = target
            target = np.where(keep, w, goal)
            if guard_exposure:
                over = float(target.sum()) > float(goal.sum()) + 1e-12
                idle = float(goal.sum()) - float(target.sum()) > band + 1e-12
                if over or idle:
                    target = goal
            delta = np.abs(target - w)
            turnover += float(delta.sum())
            pending = float((delta * c[i]).sum())
            trades += int(((w <= 1e-12) & (target > 1e-12)).sum())
            w = target.copy()
    return WeightedRun(
        pd.Series(out, index=days), pd.Series(exposure, index=days), turnover, cost, trades, stale,
        pd.Series(paid, index=days),
    )
