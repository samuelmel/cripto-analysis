"""Regra antiga "comprar no pânico", mantida só para comparação com a regra de tendência.

Congelada: é a regra que perdeu dinheiro no backtest (compra com zscore_90 < -2.5, RSI < 30 e
Fear & Greed < 25 e vende pela primeira de STOP -20%, proteger lucro, alvo, sobrecomprado ou 180 dias).
Nada aqui gera recomendação; serve de referência para `trade_simulator.performance_summary`.
Puro e vetorizado (CLAUDE.md §1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

EXIT_STOP = "STOP"
EXIT_TRAIL = "PROTEGER LUCRO"
EXIT_TARGET = "ALVO"
EXIT_OVERBOUGHT = "SOBRECOMPRADO"
EXIT_TIME = "TEMPO"

STATUS_CLOSED = "FECHADA"
STATUS_OPEN = "ABERTA"

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
    "sma_90": "float64",
    "zscore_90": "float64",
    "rsi_14": "float64",
}


@dataclass(frozen=True)
class ExitRules:
    stop_loss: float = -0.20
    trail_activation: float = 0.15
    trail_drawdown: float = 0.10
    target_zscore: float = 0.0
    overbought_rsi: float = 70.0
    max_hold_days: int = 180


@dataclass(frozen=True)
class EntryRules:
    # Dias de COMPRAR separados por até `cooldown` pertencem ao mesmo episódio: uma entrada só.
    cooldown: pd.Timedelta = pd.Timedelta(days=14)


def signal_entries(history: pd.DataFrame, rules: EntryRules = EntryRules()) -> pd.DataFrame:
    """Uma entrada por episódio de pânico: primeiro dia do episódio, ao preço de fechamento."""
    buys = history.loc[history["panic"], ["symbol", "timestamp", "close"]]
    buys = buys.sort_values(["symbol", "timestamp"])
    gap = buys.groupby("symbol", observed=True)["timestamp"].diff()
    first = buys[gap.isna() | gap.gt(rules.cooldown)]
    return pd.DataFrame(
        {
            "trade_id": first["symbol"].astype(str) + "@" + first["timestamp"].dt.strftime("%Y-%m-%d"),
            "symbol": first["symbol"].astype("string"),
            "entry_ts": first["timestamp"],
            "entry_price": first["close"],
        }
    ).reset_index(drop=True)


def panic_trades(history: pd.DataFrame) -> pd.DataFrame:
    """Operações simuladas da regra antiga (entrada no fechamento do primeiro dia de cada pânico)."""
    return simulate(signal_entries(history), history)


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

    `history`: candles com indicadores (symbol, timestamp, close, sma_90, zscore_90, rsi_14).
    `include_entry_day`: True para posições reais (compra no meio do dia: o fechamento do próprio
    dia já conta); False no backtest (entra no fechamento do dia do sinal).
    Operação sem saída até o último candle fica ABERTA, com o estado atual em last_*.
    """
    if entries.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in TRADE_SCHEMA.items()})

    cols = ["symbol", "timestamp", "close", "sma_90", "zscore_90", "rsi_14"]
    hist = history[cols].astype({"symbol": "string"}).sort_values(["symbol", "timestamp"], ignore_index=True)
    paths = _window_paths(entries, hist, rules.max_hold_days, include_entry_day)

    entry_z = entries.merge(
        hist[["symbol", "timestamp", "zscore_90"]],
        left_on=["symbol", "entry_ts"],
        right_on=["symbol", "timestamp"],
        how="left",
    ).set_index("trade_id")["zscore_90"]
    paths["entry_z"] = paths["trade_id"].map(entry_z)

    trade = paths.groupby("trade_id", sort=False)
    paths["ret"] = paths["close"] / paths["entry_price"] - 1.0
    paths["peak"] = trade["ret"].cummax()
    paths["trough"] = trade["ret"].cummin()
    paths["days"] = (paths["timestamp"] - paths["entry_ts"]).dt.days

    in_profit = paths["ret"].gt(0)
    reason = np.select(
        [
            paths["ret"].le(rules.stop_loss),
            paths["peak"].ge(rules.trail_activation)
            & (1.0 + paths["ret"]).le((1.0 + paths["peak"]) * (1.0 - rules.trail_drawdown)),
            paths["entry_z"].lt(rules.target_zscore) & paths["zscore_90"].ge(rules.target_zscore) & in_profit,
            paths["rsi_14"].ge(rules.overbought_rsi) & in_profit,
            paths["days"].ge(rules.max_hold_days),
        ],
        [EXIT_STOP, EXIT_TRAIL, EXIT_TARGET, EXIT_OVERBOUGHT, EXIT_TIME],
        default="",
    )
    paths["reason"] = reason

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
            "sma_90": last["sma_90"].reindex(out.index),
            "zscore_90": last["zscore_90"].reindex(out.index),
            "rsi_14": last["rsi_14"].reindex(out.index),
        }
    )
    return result[list(TRADE_SCHEMA)].astype(TRADE_SCHEMA).reset_index(drop=True)
