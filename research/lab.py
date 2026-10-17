"""Laboratório de estratégias: sinais puros, DCA, estatísticas de operações e referência aleatória.

Tudo aqui é função pura (sem rede, disco ou relógio); quem lê a base e grava Parquet é
`research/strategy_lab.py`. Os sinais não tocam na regra SMA 200 do painel.

Interface comum dos sinais: `signal(market, **params) -> DataFrame` com posição 0/1 por dia (linhas) e
moeda (colunas), decidida no fechamento do dia. O motor de carteira é o do pipeline
(`src.transformers.trade_simulator.run_portfolio`): a posição de t vale para o retorno de t+1, taxa de
0,1% por lado sobre cada mudança de posição.

Lookahead: as bandas e os canais de rompimento usam só dias anteriores (`shift(1)`); as médias que incluem o
fechamento de t são conhecidas no próprio fechamento de t.

ATENÇÃO (Fase 2): este estudo ainda usa o motor LEGADO (`trade_simulator.run_portfolio`): execução ao fechamento do dia do sinal,
rebalanceamento diário sem custo e só taxa. Seus números NÃO são comparáveis com os do pipeline, que usa o motor único
(`src/transformers/backtest_engine.py`). Migração prevista para a Fase 3 (validação walk-forward); até lá, leia os
resultados como históricos e exploratórios. Comparação dos motores: `research/engine_reconciliation.py`.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from src.transformers.strategies import (  # noqa: F401  (reexportados: o laboratório e os testes usam lab.X)
    RSI_PERIOD,
    VOLUME_WINDOW,
    Market,
    bollinger_reversion,
    donchian_breakout,
    latch,
    market_from_candles,
    rsi,
    rsi_oversold,
    volume_breakout,
)
from src.transformers.trade_simulator import PortfolioRun, run_portfolio

# ---------------------------------------------------------------------------------------------
# Sinais (moram em src/transformers/strategies.py, compartilhados com a seleção e a validação)
# ---------------------------------------------------------------------------------------------

Signal = Callable[..., pd.DataFrame]

# nome -> (função do sinal, candidatos de parâmetros). Escolha dos parâmetros: só no período de validação.
GRIDS: dict[str, tuple[Signal, list[dict[str, float]]]] = {
    "Donchian (rompimento)": (donchian_breakout, [{"n": n} for n in (20, 55, 100)]),
    "Bollinger (reversão)": (bollinger_reversion, [{"n": n, "k": k} for n in (20, 50) for k in (1.5, 2.0, 2.5)]),
    "RSI sobrevendido": (rsi_oversold, [{"buy_below": b, "sell_above": s} for b in (20, 25, 30, 35) for s in (50, 70)]),
    "Rompimento + volume": (volume_breakout, [{"n": n, "k": k} for n in (20, 55) for k in (1.0, 1.5, 2.0)]),
}


def describe(params: dict[str, float]) -> str:
    return ", ".join(f"{k}={v:g}" for k, v in params.items())


# ---------------------------------------------------------------------------------------------
# DCA fixo
# ---------------------------------------------------------------------------------------------

def dca_run(
    close: pd.DataFrame, valid: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, every: int, fee: float
) -> tuple[PortfolioRun, pd.Series]:
    """DCA: aporte fixo a cada `every` dias em cada moeda, a partir do primeiro dia do período com dados.

    O capital total (aportes × 1) fica parado em caixa, sem rendimento, até ser aplicado; a taxa incide sobre
    cada aporte. Devolve a carteira (peso igual entre moedas) e o retorno de cada lote até o fim do período.
    """
    px = close.where(valid).loc[start:end]
    held = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    asset = pd.DataFrame(np.nan, index=px.index, columns=px.columns)
    cost = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    lots: list[float] = []
    for symbol in px.columns:
        col = px[symbol].dropna()
        if col.empty:
            continue
        buy = pd.Series(np.arange(len(col)) % every == 0, index=col.index)
        n_buys = int(buy.sum())
        units = (buy * (1.0 - fee) / col).cumsum()
        cash = n_buys - buy.cumsum()
        equity = cash + units * col
        previous = equity.shift(1).fillna(float(n_buys))
        asset.loc[col.index, symbol] = equity / previous - 1.0
        held.loc[col.index, symbol] = (units * col) / equity
        cost.loc[col.index, symbol] = buy * fee / previous
        lots.extend(((1.0 - fee) * col.iloc[-1] / col[buy] - 1.0).tolist())
    v = px.notna()
    daily = asset.where(v).mean(axis=1, skipna=True).fillna(0.0)
    fee_cost = cost.where(v).mean(axis=1, skipna=True).fillna(0.0)
    returns = close.pct_change(fill_method=None).loc[start:end]
    run = PortfolioRun(daily, held.where(v), asset, fee_cost, pd.DataFrame(0.0, index=px.index, columns=px.columns), v, returns)
    return run, pd.Series(lots, dtype="float64")


# ---------------------------------------------------------------------------------------------
# Estatísticas de operações
# ---------------------------------------------------------------------------------------------

def _trade_summary(trade_returns: pd.Series) -> dict[str, float]:
    if trade_returns.empty:
        return {"n_trades": 0.0, "win_rate": float("nan"), "profit_factor": float("nan")}
    wins = float(trade_returns[trade_returns.gt(0)].sum())
    losses = float(-trade_returns[trade_returns.lt(0)].sum())
    return {
        "n_trades": float(len(trade_returns)),
        "win_rate": float(trade_returns.gt(0).mean()) * 100.0,
        "profit_factor": wins / losses if losses > 0 else (float("inf") if wins > 0 else float("nan")),
    }


def trade_returns(run: PortfolioRun, fee: float) -> pd.Series:
    """Retorno de cada operação (sequência contínua de dias comprado numa moeda), líquido das duas taxas.

    Operação ainda aberta no fim do período paga só a taxa de entrada (marcada a mercado).
    """
    held = run.held.fillna(0.0).gt(0)
    log_factor = np.log1p(run.returns.where(held)).where(held)
    new_run = held.ne(held.shift(1, fill_value=False))
    run_id = new_run.cumsum()
    long = pd.DataFrame(
        {"run": run_id.stack(), "log": log_factor.stack(), "held": held.stack()}
    ).reset_index(names=["day", "symbol"])
    long = long[long["held"]]
    if long.empty:
        return pd.Series(dtype="float64")
    totals = long.groupby(["symbol", "run"])["log"].sum()
    still_open = held.iloc[-1]
    last_run = run_id.iloc[-1]
    open_keys = {(str(sym), int(last_run[sym])) for sym in held.columns if bool(still_open[sym])}
    keys = [(str(s), int(r)) for s, r in totals.index]
    fee_factor = np.array([(1.0 - fee) if k in open_keys else (1.0 - fee) ** 2 for k in keys])
    return pd.Series(np.exp(totals.to_numpy()) * fee_factor - 1.0, index=totals.index)


def lab_metrics(run: PortfolioRun, fee: float, lots: pd.Series | None = None) -> dict[str, float]:
    """Métricas de uma carteira simulada: retorno, queda, Sharpe, tempo comprado, operações e custos."""
    from src.transformers.trade_simulator import summarize_returns

    if run.daily.empty:
        nan = float("nan")
        return {k: nan for k in ("total", "annual", "drawdown", "sharpe", "invested", "n_trades", "win_rate",
                                 "profit_factor", "turnover", "fee_cost")}
    base = summarize_returns(run.daily, float(run.held.where(run.valid).mean().mean()) * 100.0)
    years = len(run.daily) / 365
    stats = _trade_summary(trade_returns(run, fee) if lots is None else lots)
    n_moves = float(run.turnover.where(run.valid).sum().mean()) if lots is None else stats["n_trades"] / max(run.valid.shape[1], 1)
    return {
        "total": float(base["total"]),
        "annual": float(base["annual"]),
        "drawdown": float(base["drawdown"]),
        "sharpe": float(base["sharpe"]),
        "invested": float(base["invested"]),
        "n_trades": stats["n_trades"],
        "win_rate": stats["win_rate"],
        "profit_factor": stats["profit_factor"],
        "turnover": n_moves / years,  # mudanças de posição (entradas e saídas) por moeda por ano
        "fee_cost": float(run.fee_cost.sum()) * 100.0,  # taxa total paga, em % do capital da carteira
    }


# ---------------------------------------------------------------------------------------------
# Referência aleatória
# ---------------------------------------------------------------------------------------------

def shifted_positions(positions: pd.DataFrame, valid: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Mesma exposição e mesmas durações de operação, em outros dias: desloca circularmente cada moeda."""
    out = positions.where(valid).copy()
    for symbol in out.columns:
        mask = out[symbol].notna().to_numpy()
        values = out[symbol].to_numpy()[mask]
        if len(values) > 1:
            out.loc[mask, symbol] = np.roll(values, int(rng.integers(1, len(values))))
    return out


def random_reference(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    valid: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    fee: float,
    sims: int,
    first_seed: int,
) -> pd.DataFrame:
    """`sims` carteiras com o timing sorteado e a exposição da estratégia (sementes first_seed … first_seed+sims-1).

    Devolve uma linha por simulação com total, annual, drawdown, sharpe e invested.
    """
    window = positions.where(valid).loc[start:end]
    rows = []
    for i in range(sims):
        rng = np.random.default_rng(first_seed + i)
        run = run_portfolio(shifted_positions(window, valid.loc[start:end], rng), returns, valid, start, end, fee)
        rows.append(lab_metrics_light(run))
    return pd.DataFrame(rows)


def lab_metrics_light(run: PortfolioRun) -> dict[str, float]:
    from src.transformers.trade_simulator import summarize_returns

    if run.daily.empty:
        nan = float("nan")
        return {"total": nan, "annual": nan, "drawdown": nan, "sharpe": nan, "invested": nan}
    m = summarize_returns(run.daily, float(run.held.where(run.valid).mean().mean()) * 100.0)
    return {k: float(m[k]) for k in ("total", "annual", "drawdown", "sharpe", "invested")}
