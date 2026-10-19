"""Carteiras simuladas (sem dinheiro real) dos modelos de IA em sombra, para acompanhar o teste prospectivo.

Puro (CLAUDE.md §1). Regras fixadas em docs/paper_portfolio.md antes do primeiro dia de dados.

Cada carteira começa no primeiro dia com previsão registrada (`model_predictions.parquet`), só com dados novos:
    compra   todo dia o modelo "compra" as 5 de maior probabilidade com 1/30 do capital simulado (uma fatia por dia)
    venda    cada fatia é mantida por 30 dias (o horizonte que o modelo prevê) e depois sai
    peso     no dia D, peso da moeda = soma das fatias ativas que a contêm / 5; o que não está em fatia fica em caixa
    motor    o motor único (`backtest_engine`): decisão no fechamento de D, execução na abertura de D+1, taxa, spread e
             slippage, sem alavancagem
Referências com a MESMA regra de fatias, no mesmo período: MERCADO (todas as moedas do universo do dia, peso igual) e
MOMENTO_90D (as 5 de maior alta de 90 dias). Dia sem previsão de um modelo (ex.: sem Fear & Greed) não abre fatia.

Aprender com os erros: os modelos são retreinados todo dia com tudo o que já tem resultado conhecido (inclusive o
resultado das próprias previsões passadas, quando os 30 dias terminam). `track_record` mostra esses resultados.

Regra de parada: depois de `min_days_for_stop` dias (182), se o retorno acumulado da carteira ficar mais de
`stop_gap_pp` (15) pontos percentuais abaixo do MERCADO, o modelo é marcado DESCARTADO (continua registrando, mas sai
do placar como candidato).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest_engine import ExecutionConfig, MarketPanel, run_backtest
from .portfolio_backtest import checked, select_panel

REF_MARKET = "MERCADO"
REF_MOMENTUM = "MOMENTO_90D"
STATUS_TESTING = "EM_TESTE"
STATUS_DISCARDED = "DESCARTADO"
STATUS_TOO_EARLY = "INICIO"

MODEL_LABELS: dict[str, str] = {
    "F_LOGIT": "Logística", "F_LOGIT_SEM_FNG": "Logística sem F&G", "G_GBM": "Boosting", "G_GBM_SEM_FNG": "Boosting sem F&G",
    REF_MARKET: "Mercado", REF_MOMENTUM: "Momento 90d",
}


@dataclass(frozen=True)
class PaperRules:
    top_k: int = 5
    hold_days: int = 30
    min_days_for_stop: int = 182
    stop_gap_pp: float = 15.0


def tranche_weights(picks: pd.DataFrame, index: pd.DatetimeIndex, hold_days: int) -> pd.DataFrame:
    """Pesos-alvo diários de fatias: `picks` (dia × moeda, True = comprada naquele dia) vira o peso = fatias ativas /
    hold_days, com a fatia de cada dia (1/hold_days do capital) dividida igualmente entre as escolhidas do dia."""
    p = picks.reindex(index=index).fillna(False).astype(float)
    per_coin = p.div(p.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)  # fatia do dia dividida entre as escolhidas
    active = per_coin.rolling(hold_days, min_periods=1).sum() / hold_days
    total = active.sum(axis=1)
    return active.div(total.where(total > 1.0, 1.0), axis=0)  # nunca acima de 100%


def model_picks(log: pd.DataFrame, model: str) -> pd.DataFrame:
    """Dia × moeda: True nas moedas que o modelo compraria naquele dia (`in_top_k` do registro)."""
    part = log[log["model"].astype(str).eq(model) & log["in_top_k"].astype(bool)]
    if part.empty:
        return pd.DataFrame()
    wide = part.assign(flag=True).pivot_table(index="day", columns="symbol", values="flag", aggfunc="any")
    return wide.fillna(False).astype(bool)


def top_by(values: pd.DataFrame, member: pd.DataFrame, k: int) -> pd.DataFrame:
    v = values.where(member)
    return v.rank(axis=1, ascending=False, method="first").le(k) & v.notna()


@dataclass(frozen=True)
class PaperResult:
    equity: pd.DataFrame       # dia × carteira, patrimônio (começa em 1)
    summary: pd.DataFrame      # uma linha por carteira


SUMMARY_SCHEMA: dict[str, str] = {
    "portfolio": "string", "label": "string", "start": "datetime64[ns, UTC]", "end": "datetime64[ns, UTC]",
    "n_days": "int64", "total_return_pct": "float64", "vs_market_pp": "float64", "invested_pct": "float64",
    "cost_pct": "float64", "status": "string",
}


def run_paper(
    log: pd.DataFrame,
    panel: MarketPanel,
    member: pd.DataFrame,
    momentum: pd.DataFrame,
    cfg: ExecutionConfig,
    rules: PaperRules = PaperRules(),
    models: Sequence[str] | None = None,
) -> PaperResult:
    """Carteiras simuladas de cada modelo e das referências, do primeiro dia registrado até o último preço."""
    if log.empty:
        return PaperResult(pd.DataFrame(), pd.DataFrame({c: pd.Series(dtype=t) for c, t in SUMMARY_SCHEMA.items()}))
    start = pd.Timestamp(log["day"].min())
    end = pd.Timestamp(panel.close.index.max())
    index = pd.DatetimeIndex(panel.close.loc[start:end].index)
    if len(index) == 0:
        return PaperResult(pd.DataFrame(), pd.DataFrame({c: pd.Series(dtype=t) for c, t in SUMMARY_SCHEMA.items()}))
    names = list(models) if models is not None else sorted(log["model"].astype(str).unique())
    universe = member.reindex(index=index, columns=panel.close.columns).fillna(False).astype(bool)
    targets: dict[str, pd.DataFrame] = {}
    for name in names:
        picks = model_picks(log, name)
        if not picks.empty:
            targets[name] = tranche_weights(picks, index, rules.hold_days)
    targets[REF_MARKET] = tranche_weights(universe, index, rules.hold_days)
    mom = top_by(momentum.reindex(index=index, columns=universe.columns), universe, rules.top_k)
    targets[REF_MOMENTUM] = tranche_weights(mom, index, rules.hold_days)

    equity: dict[str, pd.Series] = {}
    rows: list[dict[str, object]] = []
    for name, t in targets.items():
        cols = [c for c in t.columns if c in panel.close.columns and t[c].abs().sum() > 0]
        if not cols:
            continue
        result = checked(run_backtest(select_panel(panel, cols), t[cols], cfg=cfg, start=start, end=end), f"simulação {name}")
        equity[name] = result.equity / cfg.initial_capital
        rows.append({"portfolio": name, "label": MODEL_LABELS.get(name, name), "start": start, "end": end, "n_days": len(result.equity),
                     "total_return_pct": (float(result.equity.iloc[-1]) / cfg.initial_capital - 1.0) * 100.0,
                     "invested_pct": float(result.exposure.mean()) * 100.0,
                     "cost_pct": float(result.trades[["fee", "spread_cost", "slippage_cost"]].to_numpy().sum()) / cfg.initial_capital * 100.0})
    eq = pd.DataFrame(equity)
    summary = pd.DataFrame(rows)
    if summary.empty:
        return PaperResult(eq, pd.DataFrame({c: pd.Series(dtype=t) for c, t in SUMMARY_SCHEMA.items()}))
    market = summary.loc[summary["portfolio"].eq(REF_MARKET), "total_return_pct"]
    market_ret = float(market.iloc[0]) if len(market) else math.nan
    summary["vs_market_pp"] = summary["total_return_pct"] - market_ret
    summary["status"] = [status(str(p), int(n), float(v), rules) for p, n, v in
                         zip(summary["portfolio"], summary["n_days"], summary["vs_market_pp"], strict=True)]
    return PaperResult(eq, summary[list(SUMMARY_SCHEMA)].astype(SUMMARY_SCHEMA))


def status(portfolio: str, n_days: int, vs_market_pp: float, rules: PaperRules) -> str:
    if portfolio in (REF_MARKET, REF_MOMENTUM):
        return "REFERENCIA"
    if n_days < rules.min_days_for_stop:
        return STATUS_TOO_EARLY if n_days < rules.hold_days else STATUS_TESTING
    return STATUS_DISCARDED if math.isfinite(vs_market_pp) and vs_market_pp < -rules.stop_gap_pp else STATUS_TESTING


TRACK_SCHEMA: dict[str, str] = {
    "model": "string", "n_mature": "int64", "hit_rate_pct": "float64", "mean_excess_pp": "float64",
}


def track_record(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Resultado das previsões já maduras de cada modelo, só das moedas que ele compraria (top-k): quantas
    superaram o BTC e quanto renderam a mais que o universo do dia, em média."""
    if outcomes.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in TRACK_SCHEMA.items()})
    top = outcomes[outcomes["in_top_k"]]
    rows = [{"model": str(m), "n_mature": len(g), "hit_rate_pct": float(g["target"].mean()) * 100.0,
             "mean_excess_pp": float((g["forward_30"] - g["universe_30"]).mean()) * 100.0} for m, g in top.groupby("model")]
    return pd.DataFrame(rows, columns=list(TRACK_SCHEMA)).astype(TRACK_SCHEMA)
