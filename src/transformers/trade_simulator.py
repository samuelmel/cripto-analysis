"""Backtest da regra de tendência: operações individuais e carteira (com taxa) contra comprar e segurar.

Puro e vetorizado (CLAUDE.md §1). Dois níveis:

    Operações (`backtest`, `simulate`)   cada entrada vira um "caminho" (os candles depois da entrada) e as
                                         regras de saída são avaliadas em todas as linhas de uma vez; a saída
                                         é a primeira linha que dispara. Servem ao gráfico, à lista de
                                         operações e às posições reais (`position_advisor`).
    Carteira (`performance_summary`)     posição de cada moeda em cada dia, peso igual entre as moedas com
                                         dados, taxa sobre cada mudança de posição. Compara a tendência com
                                         comprar e segurar e com a regra antiga do pânico.

Regra de saída (`ExitRules`), a primeira que ocorrer:
    STOP        perda de `stop_loss` sobre a entrada (opcional; ver `ExitRules.stop_loss`)
    TENDENCIA   fechou abaixo da SMA 200 da própria moeda
    MERCADO     o BTC fechou abaixo da SMA 200 (filtro de regime)

Metodologia da carteira: a posição decidida no fechamento do dia t vale para o retorno de t+1;
a taxa incide sobre a mudança de posição (cobrada no dia em que a nova posição começa a render);
todas as estratégias só começam quando a SMA 200 da moeda existe.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .panic_backtest import panic_trades

EXIT_STOP = "STOP"
EXIT_TREND = "TENDENCIA"
EXIT_REGIME = "MERCADO"

STATUS_CLOSED = "FECHADA"
STATUS_OPEN = "ABERTA"

STRATEGY_TREND = "TENDENCIA"
STRATEGY_HOLD = "COMPRAR_E_SEGURAR"
STRATEGY_PANIC = "PANICO"

# Perda de exatamente 20% (ex.: 0,50 -> 0,40) vale como STOP: sem a tolerância, 0,4/0,5 - 1 = -0,19999...
STOP_TOLERANCE = 1e-9

PERIOD_TRAIN = "TREINO"
PERIOD_TEST = "TESTE"

TRADE_SCHEMA: dict[str, str] = {
    "trade_id": "string",
    "symbol": "string",
    "entry_ts": "datetime64[ns, UTC]",
    "entry_price": "float64",
    "status": "string",
    "exit_ts": "datetime64[ns, UTC]",
    "exit_price": "float64",
    "exit_reason": "string",
    "return_pct": "float64",
    "max_return_pct": "float64",
    "min_return_pct": "float64",
    "days_held": "Int64",
    "last_ts": "datetime64[ns, UTC]",
    "last_close": "float64",
    "sma_200": "float64",
}

PERFORMANCE_SCHEMA: dict[str, str] = {
    "universe": "string",
    "strategy": "string",
    "period": "string",
    "start": "datetime64[ns, UTC]",
    "end": "datetime64[ns, UTC]",
    "total_return_pct": "float64",
    "annual_return_pct": "float64",
    "max_drawdown_pct": "float64",
    "sharpe": "float64",
    "invested_pct": "float64",
}


@dataclass(frozen=True)
class ExitRules:
    stop_loss: float | None = -0.20  # None desliga o STOP (só tendência e regime mandam sair)


# ---------------------------------------------------------------------------------------------
# Operações individuais
# ---------------------------------------------------------------------------------------------

def trend_entries(history: pd.DataFrame, symbols: tuple[str, ...]) -> pd.DataFrame:
    """Uma entrada por episódio de tendência de alta: primeiro dia, ao preço de fechamento."""
    h = history[history["symbol"].isin(list(symbols))].sort_values(["symbol", "timestamp"])
    up = h["uptrend"]
    started = up & ~up.groupby(h["symbol"]).shift(1, fill_value=False).astype(bool)
    first = h[started]
    return pd.DataFrame(
        {
            "trade_id": first["symbol"].astype(str) + "@" + first["timestamp"].dt.strftime("%Y-%m-%d"),
            "symbol": first["symbol"].astype("string"),
            "entry_ts": first["timestamp"],
            "entry_price": first["close"],
        }
    ).reset_index(drop=True)


def backtest(history: pd.DataFrame, symbols: tuple[str, ...], rules: ExitRules = ExitRules()) -> pd.DataFrame:
    """Operações da regra de tendência nas moedas `symbols`, desde o primeiro dia com SMA 200."""
    return simulate(trend_entries(history, symbols), history, rules)


def _epoch_days(ts: pd.Series) -> np.ndarray:
    """Dias desde 1970-01-01 (UTC) como inteiros."""
    naive = ts.astype("datetime64[ns, UTC]").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
    return naive.astype("datetime64[D]").astype(np.int64)


def _window_paths(entries: pd.DataFrame, hist: pd.DataFrame, max_days: int, include_entry_day: bool) -> pd.DataFrame:
    """Candles de cada operação dentro de (entrada, entrada + max_days], por índice — sem cruzar
    cada entrada com o histórico inteiro do ativo. `hist` deve vir ordenado por symbol, timestamp."""
    codes = {s: i for i, s in enumerate(pd.unique(hist["symbol"]))}
    stride = 10_000_000  # > dias desde 1970 até muito depois de 2100
    hist_days = _epoch_days(hist["timestamp"])
    hist_key = hist["symbol"].map(codes).to_numpy(dtype=np.int64) * stride + hist_days

    known = entries["symbol"].isin(codes)
    ent = entries[known]
    ent_code = ent["symbol"].map(codes).to_numpy(dtype=np.int64) * stride
    ent_days = _epoch_days(ent["entry_ts"])
    start = np.searchsorted(hist_key, ent_code + ent_days, side="left" if include_entry_day else "right")
    end = np.searchsorted(hist_key, ent_code + ent_days + max_days, side="right")
    lengths = np.maximum(end - start, 0)

    owner = np.repeat(np.arange(len(ent)), lengths)
    offsets = np.arange(lengths.sum()) - np.repeat(np.cumsum(lengths) - lengths, lengths)
    rows = hist.iloc[np.repeat(start, lengths) + offsets].reset_index(drop=True)
    trade_cols = ent[["trade_id", "entry_ts", "entry_price"]].iloc[owner].reset_index(drop=True)
    out: pd.DataFrame = pd.concat([trade_cols, rows], axis=1)
    return out


def simulate(
    entries: pd.DataFrame,
    history: pd.DataFrame,
    rules: ExitRules = ExitRules(),
    *,
    include_entry_day: bool = False,
) -> pd.DataFrame:
    """Aplica as regras de saída a cada entrada (trade_id, symbol, entry_ts, entry_price).

    `history`: candles com indicadores (symbol, timestamp, close, sma_200, regime_up).
    `include_entry_day`: True para posições reais (compra no meio do dia: o fechamento do próprio
    dia já conta); False no backtest (entra no fechamento do dia do sinal).
    Operação sem saída até o último candle fica ABERTA, com o estado atual em last_*.
    """
    if entries.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in TRADE_SCHEMA.items()})

    cols = ["symbol", "timestamp", "close", "sma_200", "regime_up"]
    hist = history[cols].astype({"symbol": "string"}).sort_values(["symbol", "timestamp"], ignore_index=True)
    horizon = int(_epoch_days(hist["timestamp"]).max() - _epoch_days(hist["timestamp"]).min()) + 1
    paths = _window_paths(entries, hist, horizon, include_entry_day)

    trade = paths.groupby("trade_id", sort=False)
    paths["ret"] = paths["close"] / paths["entry_price"] - 1.0
    paths["peak"] = trade["ret"].cummax()
    paths["trough"] = trade["ret"].cummin()
    paths["days"] = (paths["timestamp"] - paths["entry_ts"]).dt.days

    conditions = [paths["close"].lt(paths["sma_200"]), ~paths["regime_up"]]
    reasons = [EXIT_TREND, EXIT_REGIME]
    if rules.stop_loss is not None:
        conditions.insert(0, paths["ret"].le(rules.stop_loss + STOP_TOLERANCE))
        reasons.insert(0, EXIT_STOP)
    paths["reason"] = np.select(conditions, reasons, default="")

    exits = paths[paths["reason"].ne("")].groupby("trade_id", sort=False).head(1).set_index("trade_id")
    path_end = paths.groupby("trade_id", sort=False).tail(1).set_index("trade_id")

    out = entries.set_index("trade_id")
    closed = out.index.isin(exits.index)
    final = exits.reindex(out.index).where(pd.Series(closed, index=out.index), path_end.reindex(out.index), axis=0)
    # Estado atual do mercado (last_*) vem do candle mais recente do ativo, não do fim da janela.
    latest = hist.groupby("symbol", sort=False).tail(1).set_index("symbol")
    last = latest.reindex(out["symbol"].astype(str).to_numpy()).set_axis(out.index)

    result = pd.DataFrame(
        {
            "trade_id": out.index.astype("string"),
            "symbol": out["symbol"],
            "entry_ts": out["entry_ts"],
            "entry_price": out["entry_price"],
            "status": np.where(closed, STATUS_CLOSED, STATUS_OPEN),
            "exit_ts": final["timestamp"].where(closed),
            "exit_price": final["close"].where(closed),
            "exit_reason": final["reason"].where(closed),
            "return_pct": final["ret"] * 100.0,
            "max_return_pct": final["peak"] * 100.0,
            "min_return_pct": final["trough"] * 100.0,
            "days_held": final["days"],
            "last_ts": last["timestamp"].reindex(out.index),
            "last_close": last["close"].reindex(out.index),
            "sma_200": last["sma_200"].reindex(out.index),
        }
    )
    return result[list(TRADE_SCHEMA)].astype(TRADE_SCHEMA).reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# Carteira
# ---------------------------------------------------------------------------------------------

def wide(history: pd.DataFrame, column: str) -> pd.DataFrame:
    """Uma coluna do histórico em formato largo: índice = dia, colunas = moedas."""
    return history.pivot(index="timestamp", columns="symbol", values=column).sort_index()


def trend_positions(history: pd.DataFrame, rules: ExitRules = ExitRules()) -> pd.DataFrame:
    """Posição (0/1) de cada moeda em cada dia pela regra de tendência, com o STOP de `rules`.

    Sem STOP, a posição é `uptrend`. Com STOP, a posição zera no dia em que a perda sobre a entrada
    (fechamento do primeiro dia do episódio) atinge o limite e só volta no próximo episódio.
    """
    h = history.sort_values(["symbol", "timestamp"], ignore_index=True)
    up = h["uptrend"].astype(bool)
    symbol = h["symbol"]
    if rules.stop_loss is None:
        position = up
    else:
        started = up & ~up.groupby(symbol).shift(1, fill_value=False).astype(bool)
        run = started.astype(int).groupby(symbol).cumsum()
        entry_close = h["close"].where(started).groupby(symbol).ffill()
        hit = (up & (h["close"] / entry_close - 1.0).le(rules.stop_loss + STOP_TOLERANCE)).astype(int)
        stopped = hit.groupby([symbol, run]).cummax().astype(bool)
        position = up & ~stopped
    return wide(h.assign(position=position.astype(float)), "position")


def positions_from_trades(trades: pd.DataFrame, index: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    """Posição (0/1) por moeda e dia: comprado de `entry_ts` (inclusive) até `exit_ts` (exclusive)."""
    opened = trades.assign(ts=trades["entry_ts"], delta=1)
    ended = trades[trades["exit_ts"].notna()].assign(ts=lambda t: t["exit_ts"], delta=-1)
    events = pd.concat([opened[["ts", "symbol", "delta"]], ended[["ts", "symbol", "delta"]]], ignore_index=True)
    steps = events.groupby(["ts", "symbol"])["delta"].sum().unstack("symbol")
    steps = steps.reindex(index=index, columns=columns).fillna(0.0)
    return steps.cumsum().gt(0).astype(float)


@dataclass(frozen=True)
class PortfolioRun:
    """Carteira de peso igual simulada num período: base de `evaluate_portfolio` e do laboratório (`research/`)."""

    daily: pd.Series         # retorno diário da carteira, já líquido de taxa
    held: pd.DataFrame       # posição carregada em cada dia (a decidida em t-1), por moeda
    asset_daily: pd.DataFrame  # retorno diário líquido de cada moeda (NaN onde a SMA 200 ainda não existe)
    fee_cost: pd.Series      # taxa paga em cada dia, como fração do capital da carteira
    turnover: pd.DataFrame   # |mudança de posição| decidida em cada dia, por moeda
    valid: pd.DataFrame      # onde a moeda tem dados (SMA 200 existe)
    returns: pd.DataFrame    # retorno diário bruto de cada moeda no período


def run_portfolio(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    valid: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    fee: float,
) -> PortfolioRun:
    """Aplica a metodologia da carteira (posição de t vale para t+1, taxa sobre a mudança) em [start, end]."""
    p = positions.where(valid).loc[start:end]
    r = returns.loc[start:end]
    v = valid.loc[start:end]
    held = p.shift(1)  # decide no fechamento de t, ganha o retorno de t+1
    turnover = p.diff().abs().fillna(0.0)
    fee_drag = turnover.shift(1).fillna(0.0) * fee
    daily = held * r - fee_drag
    port = daily.where(v).mean(axis=1, skipna=True).fillna(0.0)
    cost = fee_drag.where(v).mean(axis=1, skipna=True).fillna(0.0)
    return PortfolioRun(port, held, daily.where(v), cost, turnover, v, r)


def summarize_returns(port: pd.Series, invested_pct: float) -> dict[str, float | pd.Timestamp]:
    """Retorno total e anual, pior queda e Sharpe de uma série de retornos diários de cripto (365 dias por ano)."""
    equity = (1.0 + port).cumprod()
    years = len(port) / 365
    vol = float(port.std() * np.sqrt(365))
    return {
        "start": pd.Timestamp(port.index[0]),
        "end": pd.Timestamp(port.index[-1]),
        "total": float(equity.iloc[-1] - 1.0) * 100.0,
        "annual": (float(equity.iloc[-1]) ** (1.0 / years) - 1.0) * 100.0,
        "drawdown": float((equity / equity.cummax() - 1.0).min()) * 100.0,
        "sharpe": float(port.mean() * 365) / vol if vol > 0 else float("nan"),
        "invested": invested_pct,
    }


def evaluate_portfolio(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    valid: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    fee: float,
) -> dict[str, float | pd.Timestamp]:
    """Métricas da carteira de peso igual entre as moedas com dados, no período [start, end]."""
    run = run_portfolio(positions, returns, valid, start, end, fee)
    if run.daily.empty:
        nan = float("nan")
        return {"start": start, "end": end, "total": nan, "annual": nan, "drawdown": nan, "sharpe": nan, "invested": nan}
    return summarize_returns(run.daily, float(run.held.where(run.valid).mean().mean()) * 100.0)


def performance_summary(
    history: pd.DataFrame,
    universes: dict[str, tuple[str, ...]],
    periods: dict[str, tuple[pd.Timestamp, pd.Timestamp]],
    fee: float,
    rules: ExitRules = ExitRules(),
) -> pd.DataFrame:
    """Tendência x comprar e segurar x pânico (regra antiga), por universo e período (PERFORMANCE_SCHEMA).

    `universes`: nome -> moedas da carteira. `periods`: nome -> (início, fim) inclusive.
    """
    closes = wide(history, "close")
    returns = closes.pct_change(fill_method=None)
    valid = wide(history, "sma_200").notna()
    strategies = {
        STRATEGY_TREND: trend_positions(history, rules).reindex_like(closes),
        STRATEGY_HOLD: pd.DataFrame(1.0, index=closes.index, columns=closes.columns),
        STRATEGY_PANIC: positions_from_trades(panic_trades(history), pd.DatetimeIndex(closes.index), closes.columns),
    }
    rows: list[dict[str, object]] = []
    for universe, symbols in universes.items():
        cols = [s for s in symbols if s in closes.columns]
        for strategy, positions in strategies.items():
            for period, (start, end) in periods.items():
                m = evaluate_portfolio(positions[cols], returns[cols], valid[cols], start, end, fee)
                rows.append(
                    {
                        "universe": universe, "strategy": strategy, "period": period,
                        "start": m["start"], "end": m["end"],
                        "total_return_pct": m["total"], "annual_return_pct": m["annual"],
                        "max_drawdown_pct": m["drawdown"], "sharpe": m["sharpe"], "invested_pct": m["invested"],
                    }
                )
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in PERFORMANCE_SCHEMA.items()})
    return pd.DataFrame(rows)[list(PERFORMANCE_SCHEMA)].astype(PERFORMANCE_SCHEMA)
