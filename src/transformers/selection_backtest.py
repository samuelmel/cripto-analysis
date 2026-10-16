"""Backtest da camada de seleção em carteira, contra referências simples, com custos.

Puro (CLAUDE.md §1). A seleção de cada dia de rebalanceamento é a MESMA função do pipeline (`selection.assess`
+ `allocation.allocate`, com o orçamento configurado, arredondamento e ordem mínima), então o teste mede o que o
painel recomenda, não uma versão simplificada.

Motor (`run_weighted`): pesos-alvo decididos no fechamento do dia t passam a valer no retorno de t+1; entre
rebalanceamentos os pesos flutuam com os preços (sem rebalanceamento implícito); moeda que continua na carteira
só é reajustada se o alvo mudar mais que config.REBALANCE_BAND; o custo de cada troca é
|mudança de peso| × (taxa + spread estimado + slippage) da moeda, cobrado no dia em que a nova posição começa a
render. O que não está alocado fica em caixa, sem rendimento.

Estratégias:
    SELECAO              seleção + aporte variável (dimensionamento por volatilidade), como no pipeline
    SELECAO_PESO_IGUAL   a mesma seleção, com o mesmo valor (1/MAX_POSITIONS) para cada moeda: isola o efeito do
                         dimensionamento
    MOMENTO_SIMPLES      as MAX_CANDIDATES de maior retorno em 90 dias (com dado no dia), peso igual, sem filtro
    TENDENCIA_SMA200     regra principal: moeda e BTC acima da SMA 200, peso igual entre as moedas com SMA 200
    COMPRAR_E_SEGURAR    todas as moedas com SMA 200, peso igual
    BTC                  só Bitcoin, comprado e segurado
Todas são rebalanceadas a cada `every` dias (a regra SMA 200 aqui fica semanal; a versão diária, com o motor
original, continua em performance.parquet).

Limitações: o universo são as moedas que existem hoje (viés de sobrevivência); spread e slippage são hipóteses
(config.SPREAD_TIERS, config.SLIPPAGE), não medidas; execução no fechamento; sem impostos.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config
from .allocation import AllocationRules, allocate
from .selection import (
    REGIME_DEFENSIVE,
    SelectionRules,
    as_float,
    assess,
    features_on,
)
from .trade_simulator import summarize_returns

STRATEGY_SELECTION = "SELECAO"
STRATEGY_SELECTION_EQUAL = "SELECAO_PESO_IGUAL"
STRATEGY_MOMENTUM = "MOMENTO_SIMPLES"
STRATEGY_SMA200 = "TENDENCIA_SMA200"
STRATEGY_HOLD_ALL = "COMPRAR_E_SEGURAR"
STRATEGY_BTC = "BTC"
SELECTION_STRATEGIES: tuple[str, ...] = (
    STRATEGY_SELECTION, STRATEGY_SELECTION_EQUAL, STRATEGY_MOMENTUM, STRATEGY_SMA200, STRATEGY_HOLD_ALL, STRATEGY_BTC,
)

SELECTION_PERF_SCHEMA: dict[str, str] = {
    "strategy": "string",
    "period": "string",
    "start": "datetime64[ns, UTC]",
    "end": "datetime64[ns, UTC]",
    "total_return_pct": "float64",
    "annual_return_pct": "float64",
    "max_drawdown_pct": "float64",
    "sharpe": "float64",
    "invested_pct": "float64",      # exposição média (% do capital comprado)
    "turnover_per_year": "float64", # soma de |mudança de peso| por ano (1 = trocar a carteira inteira uma vez)
    "n_trades": "Int64",            # entradas em moedas (de 0 para > 0)
    "cost_pct": "float64",          # custos pagos (taxa, spread, slippage), em % do capital, somados no período
    "rebalance_days": "Int64",
}


ENGINE_VERSION = "weights-2"
"""1: faixa de tolerância sem limite de exposição (podia passar de 100% ou deixar caixa parado). 2: com guarda de
exposição (ver `run_weighted`). Entra na configuração dos experimentos de pesquisa."""


@dataclass(frozen=True)
class WeightedRun:
    daily: pd.Series        # retorno diário da carteira, líquido de custos
    exposure: pd.Series     # soma dos pesos carregados em cada dia
    turnover: float         # soma de |mudança de peso| nos rebalanceamentos
    cost: float             # custos totais, fração do capital
    n_trades: int
    stale_weight_days: float = 0.0  # Σ peso × dias em que a moeda carregada não tinha preço (retorno tratado como 0)


def run_weighted(
    targets: pd.DataFrame,
    returns: pd.DataFrame,
    cost_per_side: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    band: float = config.REBALANCE_BAND,
    guard_exposure: bool = True,
) -> WeightedRun:
    """Simula pesos-alvo (`targets`: linhas = dias de rebalanceamento, valores = fração do capital) em [start, end].

    `band`: moeda mantida (peso atual e alvo > 0) só é reajustada se |alvo − atual| > band.

    `guard_exposure` (padrão, `ENGINE_VERSION` 2): a faixa não pode produzir uma carteira com exposição total acima
    da exposição-alvo (alavancagem implícita: moedas mantidas ficam acima do alvo enquanto a nova entra no alvo) nem
    mais de `band` abaixo dela (caixa parado: o dinheiro de uma moeda que saiu não era reinvestido). Nesses casos o
    rebalanceamento vai direto aos alvos. `False` reproduz o motor da versão 1, só para comparação.

    Dia sem preço de uma moeda carregada: o retorno é tratado como 0 (o preço fica parado) e o peso exposto é somado
    em `stale_weight_days`. Não há perda por deslistagem: é viés de sobrevivência, sinalizado, não corrigido.
    """
    days = returns.loc[start:end].index
    cols = list(returns.columns)
    if len(days) == 0:
        empty = pd.Series(dtype="float64")
        return WeightedRun(empty, empty, 0.0, 0.0, 0)
    raw = returns.reindex(index=days, columns=cols).to_numpy(dtype="float64")
    missing = np.isnan(raw)
    r = np.where(missing, 0.0, raw)
    stale = 0.0
    c = cost_per_side.reindex(index=days, columns=cols).ffill().fillna(0.0).to_numpy(dtype="float64")
    t = targets.reindex(columns=cols).fillna(0.0)
    plan = {pd.Timestamp(d): row for d, row in zip(t.index, t.to_numpy(dtype="float64"), strict=True)}

    w = np.zeros(len(cols))
    pending = 0.0
    out = np.zeros(len(days))
    exposure = np.zeros(len(days))
    turnover = cost = 0.0
    trades = 0
    for i, day in enumerate(days):
        gross = float(w @ r[i])
        stale += float(w @ missing[i])
        out[i] = (1.0 - pending) * (1.0 + gross) - 1.0
        exposure[i] = float(w.sum())
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
    return WeightedRun(pd.Series(out, index=days), pd.Series(exposure, index=days), turnover, cost, trades, stale)


def rebalance_days(features: pd.DataFrame, every: int) -> pd.DatetimeIndex:
    days = features.index.get_level_values("timestamp").unique().sort_values()
    return pd.DatetimeIndex(days[::every])


@dataclass(frozen=True)
class SelectionTargets:
    variable: pd.DataFrame     # SELECAO
    equal: pd.DataFrame        # SELECAO_PESO_IGUAL
    funded_days: int           # rebalanceamentos com algum aporte
    zeroed_small: int          # aportes zerados por ordem mínima ou custo
    capped_days: int           # rebalanceamentos em que a exposição-alvo passou do orçamento


def selection_targets(
    features: pd.DataFrame,
    regime: pd.Series,
    days: Sequence[pd.Timestamp],
    budget: float,
    sel_rules: SelectionRules = SelectionRules(),
    alloc_rules: AllocationRules = AllocationRules(),
) -> SelectionTargets:
    """Pesos da seleção em cada dia de `days`, com a alocação do pipeline (valores em reais / orçamento)."""
    symbols = list(features.index.get_level_values("symbol").unique())
    variable = pd.DataFrame(0.0, index=pd.DatetimeIndex(list(days)), columns=symbols)
    equal = variable.copy()
    funded = zeroed = capped = 0
    share = 1.0 / alloc_rules.max_positions if alloc_rules.max_positions > 0 else 0.0
    for day in days:
        assessed = assess(features_on(features, day), str(regime.get(day, "INDISPONIVEL")), sel_rules)
        alloc, summary = allocate(assessed, budget, str(regime.get(day, "INDISPONIVEL")), alloc_rules)
        if budget > 0:
            variable.loc[day, alloc["symbol"].tolist()] = (alloc["allocation_brl"] / budget).to_numpy()
        top = assessed.loc[assessed["selected"], "symbol"].head(alloc_rules.max_positions).tolist()
        factor = alloc_rules.regime_reduce_factor if (
            str(regime.get(day, "")) == REGIME_DEFENSIVE and alloc_rules.regime_filter == "reduzir"
        ) else 1.0
        equal.loc[day, top] = share * factor
        funded += int(summary.total_brl > 0)
        capped += int(summary.capped_by_budget)
        zeroed += int(alloc["allocation_note"].fillna("").str.contains("impraticável|inviável").sum())
    return SelectionTargets(variable, equal, funded, zeroed, capped)


def baseline_targets(
    features: pd.DataFrame,
    regime_symbol: str,
    days: Sequence[pd.Timestamp],
    top_n: int,
) -> dict[str, pd.DataFrame]:
    """Pesos das referências simples em cada dia de `days`."""
    idx = pd.DatetimeIndex(list(days))

    def wide(col: str) -> pd.DataFrame:
        frame = features[col].unstack("symbol").reindex(idx)
        return pd.DataFrame(frame)

    has = wide("has_candle").fillna(False).astype(bool)
    sma200 = wide("sma_200")
    close = wide("close")
    valid = has & sma200.notna()
    n_valid = valid.sum(axis=1).replace(0, np.nan)
    above = valid & close.gt(sma200)
    btc_up = above[regime_symbol] if regime_symbol in above.columns else pd.Series(False, index=idx)
    trend = above & btc_up.to_numpy()[:, None]
    r90 = wide("ret_90d_pct").where(has)
    rank = r90.rank(axis=1, ascending=False, method="first")
    top = rank.le(top_n)
    btc = pd.DataFrame(0.0, index=idx, columns=close.columns)
    if regime_symbol in btc.columns:
        btc[regime_symbol] = valid[regime_symbol].astype(float)
    return {
        STRATEGY_MOMENTUM: top.astype(float) / top_n,
        STRATEGY_SMA200: trend.astype(float).div(n_valid, axis=0).fillna(0.0),
        STRATEGY_HOLD_ALL: valid.astype(float).div(n_valid, axis=0).fillna(0.0),
        STRATEGY_BTC: btc,
    }


def market_returns(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retornos diários (preço com lacunas internas preenchidas) e custo por lado, em formato largo."""
    close = pd.DataFrame(features["close"].unstack("symbol")).sort_index()
    cost = pd.DataFrame(features["cost_per_side"].unstack("symbol")).sort_index()
    return close.pct_change(fill_method=None), cost


def metrics_row(strategy: str, period: str, run: WeightedRun, every: int) -> dict[str, object]:
    if run.daily.empty:
        nan = float("nan")
        return {"strategy": strategy, "period": period, "start": pd.NaT, "end": pd.NaT, "total_return_pct": nan,
                "annual_return_pct": nan, "max_drawdown_pct": nan, "sharpe": nan, "invested_pct": nan,
                "turnover_per_year": nan, "n_trades": 0, "cost_pct": nan, "rebalance_days": every}
    m = summarize_returns(run.daily, float(run.exposure.mean()) * 100.0)
    years = len(run.daily) / 365
    return {
        "strategy": strategy, "period": period, "start": m["start"], "end": m["end"],
        "total_return_pct": m["total"], "annual_return_pct": m["annual"], "max_drawdown_pct": m["drawdown"],
        "sharpe": m["sharpe"], "invested_pct": m["invested"], "turnover_per_year": run.turnover / years,
        "n_trades": run.n_trades, "cost_pct": run.cost * 100.0, "rebalance_days": every,
    }


def evaluate_selection(
    features: pd.DataFrame,
    regime: pd.Series,
    periods: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
    budget: float,
    every: int,
    sel_rules: SelectionRules = SelectionRules(),
    alloc_rules: AllocationRules = AllocationRules(),
) -> tuple[pd.DataFrame, SelectionTargets]:
    """Métricas (SELECTION_PERF_SCHEMA) de todas as estratégias em cada período, e os pesos da seleção."""
    first = min(s for s, _ in periods.values())
    days = [d for d in rebalance_days(features, every) if d >= first - pd.Timedelta(days=every)]
    sel = selection_targets(features, regime, days, budget, sel_rules, alloc_rules)
    targets = {
        STRATEGY_SELECTION: sel.variable,
        STRATEGY_SELECTION_EQUAL: sel.equal,
        **baseline_targets(features, sel_rules.regime_symbol, days, sel_rules.max_candidates),
    }
    returns, cost = market_returns(features)
    rows = [
        metrics_row(name, period, run_weighted(weights, returns, cost, start, end), every)
        for name, weights in targets.items()
        for period, (start, end) in periods.items()
    ]
    return pd.DataFrame(rows)[list(SELECTION_PERF_SCHEMA)].astype(SELECTION_PERF_SCHEMA), sel


def evidence(perf: pd.DataFrame, period: str) -> str:
    """Uma frase sobre o que o período de teste mostrou, comparando a seleção com as referências simples."""
    test = perf[perf["period"].eq(period)]
    sharpe = {str(k): as_float(v) for k, v in zip(test["strategy"], test["sharpe"], strict=True)}
    own = sharpe.get(STRATEGY_SELECTION, float("nan"))
    if not np.isfinite(own):
        return "Sem validação histórica disponível para a seleção nesta execução."
    row = test[test["strategy"].eq(STRATEGY_SELECTION)].iloc[0]
    refs = [x for x in (STRATEGY_HOLD_ALL, STRATEGY_MOMENTUM, STRATEGY_SMA200, STRATEGY_BTC) if np.isfinite(sharpe.get(x, np.nan))]
    beaten = [x for x in refs if own > sharpe[x]]
    names = {STRATEGY_HOLD_ALL: "comprar e segurar todas", STRATEGY_MOMENTUM: "momento simples",
             STRATEGY_SMA200: "regra SMA 200", STRATEGY_BTC: "só Bitcoin"}

    def num(x: float, d: int = 1) -> str:
        return f"{x:.{d}f}".replace(".", ",")

    head = (
        f"No período de teste ({pd.Timestamp(str(row['start'])):%Y} em diante; já consultado antes, não é prospectivo), a seleção teve Sharpe {num(own)}, "
        f"retorno de {num(as_float(row['annual_return_pct']))}% ao ano e pior queda de {num(as_float(row['max_drawdown_pct']), 0)}%"
    )
    if len(beaten) == len(refs):
        verdict = "; superou, em retorno por risco, todas as referências simples, sem garantia de repetir."
    elif beaten:
        lost = [names[x] for x in refs if x not in beaten]
        verdict = f"; não superou {', '.join(lost)} em retorno por risco, então a vantagem não está demonstrada."
    else:
        verdict = "; não superou nenhuma referência simples em retorno por risco: a vantagem não está demonstrada."
    return head + verdict
