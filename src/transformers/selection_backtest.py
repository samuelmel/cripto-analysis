"""Backtest da camada de seleção em carteira, contra referências simples, com custos.

Puro (CLAUDE.md §1). A seleção de cada dia de rebalanceamento é a MESMA função do pipeline (`selection.assess`
+ `allocation.allocate`, com o orçamento configurado, arredondamento e ordem mínima), então o teste mede o que o
painel recomenda, não uma versão simplificada.

Motor: `evaluate_selection` usa o motor único (`backtest_engine.py`: sinal no fechamento de D, execução na abertura
de D+1, caixa e quantidades, custos do `costs.py`, universo point-in-time). O motor antigo abaixo (`run_weighted`)
e `evaluate_selection_legacy` ficam só para reproduzir os resultados anteriores à Fase 2.

Motor LEGADO (`run_weighted`): pesos-alvo decididos no fechamento do dia t passam a valer no retorno de t+1; entre
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

Universo: com `eligible` (universo point-in-time), a seleção e as referências só consideram, em cada dia, as moedas
elegíveis naquele dia (correção da Fase 3: antes, a referência escolhia também moedas fora do universo, cujo alvo o
motor zerava, e ficava parcialmente em caixa sem que isso fosse a regra; ver docs/QUANT_ROADMAP_PROGRESS.md).

Limitações: as candidatas do pipeline são as moedas de `config.UNIVERSE` (viés de sobrevivência da lista; a base
completa do arquivo está na pesquisa); spread e slippage são hipóteses (config.SPREAD_TIERS, config.SLIPPAGE), não
medidas; a abertura seguinte é uma aproximação do preço alcançável; sem impostos.
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
from .backtest_engine import BacktestResult, ExecutionConfig, MarketPanel, run_backtest, summarize
from .bootstrap import BootstrapConfig, bootstrap_difference, make_resampler, sharpe_stat
from .portfolio_backtest import checked, select_panel
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


@dataclass(frozen=True)
class WeightedRun:
    daily: pd.Series        # retorno diário da carteira, líquido de custos
    exposure: pd.Series     # soma dos pesos carregados em cada dia
    turnover: float         # soma de |mudança de peso| nos rebalanceamentos
    cost: float             # custos totais, fração do capital
    n_trades: int


def run_weighted(
    targets: pd.DataFrame,
    returns: pd.DataFrame,
    cost_per_side: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    band: float = config.REBALANCE_BAND,
) -> WeightedRun:
    """LEGADO (pode passar de 100% de exposição com a banda; ver tests/test_engine_reconciliation.py). Use
    `backtest_engine.run_backtest`. Simula pesos-alvo (linhas = dias de rebalanceamento) em [start, end].

    `band`: moeda mantida (peso atual e alvo > 0) só é reajustada se |alvo − atual| > band.
    """
    days = returns.loc[start:end].index
    cols = list(returns.columns)
    if len(days) == 0:
        empty = pd.Series(dtype="float64")
        return WeightedRun(empty, empty, 0.0, 0.0, 0)
    r = returns.reindex(index=days, columns=cols).fillna(0.0).to_numpy(dtype="float64")
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
            target = np.where(keep, w, target)
            delta = np.abs(target - w)
            turnover += float(delta.sum())
            pending = float((delta * c[i]).sum())
            trades += int(((w <= 1e-12) & (target > 1e-12)).sum())
            w = target.copy()
    return WeightedRun(pd.Series(out, index=days), pd.Series(exposure, index=days), turnover, cost, trades)


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
    eligible: pd.DataFrame | None = None,
) -> SelectionTargets:
    """Pesos da seleção em cada dia de `days`, com a alocação do pipeline (valores em reais / orçamento).

    `eligible` (universo point-in-time, dias x moedas): só as moedas elegíveis no dia são avaliadas, como no
    pipeline ao vivo, em que `universe.select_universe` decide antes da seleção quem é analisado. Sem isso, uma
    moeda fora do universo podia ocupar uma das vagas e o motor zerava o alvo dela (vaga desperdiçada em caixa).
    """
    symbols = list(features.index.get_level_values("symbol").unique())
    variable = pd.DataFrame(0.0, index=pd.DatetimeIndex(list(days)), columns=symbols)
    equal = variable.copy()
    funded = zeroed = capped = 0
    share = 1.0 / alloc_rules.max_positions if alloc_rules.max_positions > 0 else 0.0
    for day in days:
        assessed = assess(_eligible_rows(features_on(features, day), eligible, day), str(regime.get(day, "INDISPONIVEL")), sel_rules)
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


def _eligible_rows(day_features: pd.DataFrame, eligible: pd.DataFrame | None, day: pd.Timestamp) -> pd.DataFrame:
    """As linhas de `features_on` das moedas elegíveis em `day` (todas, sem `eligible`)."""
    if eligible is None or day_features.empty:
        return day_features
    if day not in eligible.index:
        return day_features.iloc[0:0]
    ok = eligible.loc[day].reindex(day_features.index).fillna(False).astype(bool)
    return day_features[ok.to_numpy()]


def baseline_targets(
    features: pd.DataFrame,
    regime_symbol: str,
    days: Sequence[pd.Timestamp],
    top_n: int,
    eligible: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Pesos das referências simples em cada dia de `days`. Com `eligible`, só moedas elegíveis no dia contam
    (no sorteio do momento e no N do peso igual), para a referência não ficar parcialmente em caixa por escolher
    moedas que o motor não pode comprar."""
    idx = pd.DatetimeIndex(list(days))

    def wide(col: str) -> pd.DataFrame:
        frame = features[col].unstack("symbol").reindex(idx)
        return pd.DataFrame(frame)

    has = wide("has_candle").fillna(False).astype(bool)
    if eligible is not None:
        has = has & eligible.reindex(index=idx, columns=has.columns).fillna(False).astype(bool)
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


def _all_targets(
    features: pd.DataFrame,
    regime: pd.Series,
    periods: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
    budget: float,
    every: int,
    sel_rules: SelectionRules,
    alloc_rules: AllocationRules,
    eligible: pd.DataFrame | None = None,
) -> tuple[dict[str, pd.DataFrame], SelectionTargets]:
    first = min(s for s, _ in periods.values())
    days = [d for d in rebalance_days(features, every) if d >= first - pd.Timedelta(days=every)]
    sel = selection_targets(features, regime, days, budget, sel_rules, alloc_rules, eligible)
    targets = {
        STRATEGY_SELECTION: sel.variable,
        STRATEGY_SELECTION_EQUAL: sel.equal,
        **baseline_targets(features, sel_rules.regime_symbol, days, sel_rules.max_candidates, eligible),
    }
    return targets, sel


def engine_metrics_row(strategy: str, period: str, result: BacktestResult, every: int) -> dict[str, object]:
    """Uma linha de SELECTION_PERF_SCHEMA a partir do motor único."""
    m = summarize(result)
    return {
        "strategy": strategy, "period": period, "start": m["start"], "end": m["end"],
        "total_return_pct": m["total"], "annual_return_pct": m["annual"], "max_drawdown_pct": m["drawdown"],
        "sharpe": m["sharpe"], "invested_pct": m["invested"], "turnover_per_year": m["turnover_per_year"],
        "n_trades": int(float(m["n_trades"])), "cost_pct": m["cost_pct"], "rebalance_days": every,
    }


def evaluate_selection(
    features: pd.DataFrame,
    regime: pd.Series,
    periods: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
    budget: float,
    every: int,
    panel: MarketPanel,
    cfg: ExecutionConfig,
    *,
    eligible: pd.DataFrame | None = None,
    sel_rules: SelectionRules = SelectionRules(),
    alloc_rules: AllocationRules = AllocationRules(),
) -> tuple[pd.DataFrame, SelectionTargets]:
    """Métricas (SELECTION_PERF_SCHEMA) de todas as estratégias em cada período no motor único, com as mesmas
    premissas de execução, custos e universo (`eligible`) para a seleção e para cada referência."""
    perf, sel, _ = evaluate_selection_runs(features, regime, periods, budget, every, panel, cfg, eligible=eligible,
                                           sel_rules=sel_rules, alloc_rules=alloc_rules)
    return perf, sel


def evaluate_selection_runs(
    features: pd.DataFrame,
    regime: pd.Series,
    periods: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
    budget: float,
    every: int,
    panel: MarketPanel,
    cfg: ExecutionConfig,
    *,
    eligible: pd.DataFrame | None = None,
    sel_rules: SelectionRules = SelectionRules(),
    alloc_rules: AllocationRules = AllocationRules(),
) -> tuple[pd.DataFrame, SelectionTargets, dict[tuple[str, str], BacktestResult]]:
    """`evaluate_selection` com as simulações de cada (estratégia, período), para medir a incerteza."""
    targets, sel = _all_targets(features, regime, periods, budget, every, sel_rules, alloc_rules, eligible)
    rows = []
    runs: dict[tuple[str, str], BacktestResult] = {}
    for name, weights in targets.items():
        sub = select_panel(panel, list(weights.columns))
        for period, (start, end) in periods.items():
            result = checked(run_backtest(sub, weights, eligible=eligible, cfg=cfg, start=start, end=end), f"{name}/{period}")
            runs[(name, period)] = result
            rows.append(engine_metrics_row(name, period, result, every))
    return pd.DataFrame(rows)[list(SELECTION_PERF_SCHEMA)].astype(SELECTION_PERF_SCHEMA), sel, runs


def evaluate_selection_legacy(
    features: pd.DataFrame,
    regime: pd.Series,
    periods: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
    budget: float,
    every: int,
    sel_rules: SelectionRules = SelectionRules(),
    alloc_rules: AllocationRules = AllocationRules(),
) -> tuple[pd.DataFrame, SelectionTargets]:
    """LEGADO (motor `run_weighted`, premissas anteriores à Fase 2). Mantido só para reproduzir resultados antigos;
    não usar em resultado novo. Métricas (SELECTION_PERF_SCHEMA) de todas as estratégias em cada período."""
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
    """Uma frase sobre o que o teste fora da amostra mostrou, comparando a seleção com as referências simples."""
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
        f"No teste fora da amostra ({pd.Timestamp(str(row['start'])):%Y} em diante), a seleção teve Sharpe {num(own)}, "
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


MIN_EVIDENCE_DAYS = 365


def evidence_with_uncertainty(
    perf: pd.DataFrame,
    runs: Mapping[tuple[str, str], BacktestResult],
    period: str,
    boot: BootstrapConfig = BootstrapConfig(n_boot=1000),
) -> str:
    """Frase de evidência da seleção (Fase 3): Sharpe, retorno e queda do período, e a diferença de Sharpe contra
    comprar e segurar as MESMAS moedas (mesmo universo e premissas) com intervalo de 90% por bootstrap
    estacionário pareado. Substitui a comparação de Sharpe pontuais de `evidence`.

    É UMA comparação pré-declarada sobre um período já consultado no desenvolvimento (2023 em diante): não é
    teste intocado, não tem correção para as várias estratégias que o projeto testou (isso está em
    `research/validation_study.py`) e não promete nada.
    """
    own = runs.get((STRATEGY_SELECTION, period))
    ref = runs.get((STRATEGY_HOLD_ALL, period))
    test = perf[perf["period"].eq(period) & perf["strategy"].eq(STRATEGY_SELECTION)]
    if own is None or ref is None or test.empty or own.returns.empty or not np.isfinite(as_float(test.iloc[0]["sharpe"])):
        return "Sem validação histórica disponível para a seleção nesta execução."
    row = test.iloc[0]

    def num(x: float, d: int = 1) -> str:
        return f"{x:.{d}f}".replace(".", ",")

    def signed(x: float) -> str:
        return ("+" if x > 0 else "-" if x < 0 else "") + num(abs(x), 2)

    head = (
        f"No período de {pd.Timestamp(str(row['start'])):%Y} em diante (já consultado durante o desenvolvimento: não "
        f"é um teste intocado), a seleção teve Sharpe {num(as_float(row['sharpe']))}, retorno de "
        f"{num(as_float(row['annual_return_pct']))}% ao ano e pior queda de {num(as_float(row['max_drawdown_pct']), 0)}%."
    )
    x = own.returns.to_numpy(dtype="float64")
    y = ref.returns.reindex(own.returns.index).to_numpy(dtype="float64")
    if len(x) < MIN_EVIDENCE_DAYS or not np.isfinite(y).all():
        return head + " Amostra curta demais para medir a incerteza: a vantagem não está demonstrada."
    res = make_resampler([x, y], boot)
    d = bootstrap_difference(x, y, sharpe_stat(), res)
    if not np.isfinite(d.estimate):
        return head + " Sem diferença de Sharpe calculável contra a referência: a vantagem não está demonstrada."
    body = (f" Diferença de Sharpe contra comprar e segurar as mesmas moedas: {signed(d.estimate)} (intervalo de 90%: "
            f"{signed(d.ci_low)} a {signed(d.ci_high)}; bootstrap em blocos de ~{d.block:.0f} dias).")
    if d.ci_low > 0:
        verdict = (" Acima da referência neste período, sem correção para as várias estratégias testadas e sem "
                   "confirmação em dados novos.")
    elif d.ci_high < 0:
        verdict = " Abaixo da referência neste período."
    else:
        verdict = " Diferença compatível com sorte: a vantagem não está demonstrada."
    return head + body + verdict
