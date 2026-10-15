"""Recomendação para posições reais: VENDER (com motivo e desde quando) ou SEGURAR.

Usa as mesmas regras de saída do backtest (`trade_simulator`): vender ao fechar abaixo da SMA 200
da moeda, ou quando o BTC fecha abaixo da dele, ou na perda de 20% sobre o preço pago.

O STOP é permanente: uma vez atingido, a posição segue como VENDER. As saídas por tendência e por
mercado valem pelo estado de hoje: se a moeda voltou a fechar acima da SMA 200 (e o BTC também), a
posição volta a SEGURAR; `signal_ts` é o primeiro dia da sequência atual de fechamentos contra a regra
(ou o dia da compra, se for mais recente). Puro (CLAUDE.md §1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .trade_simulator import EXIT_REGIME, EXIT_STOP, EXIT_TREND, ExitRules

ACTION_SELL = "VENDER"
ACTION_HOLD = "SEGURAR"

POSITION_SCHEMA: dict[str, str] = {
    "position_id": "string",
    "symbol": "string",
    "entry_ts": "datetime64[ns, UTC]",
    "entry_price": "float64",
    "qty": "float64",
    "last_ts": "datetime64[ns, UTC]",
    "last_close": "float64",
    "return_pct": "float64",        # resultado atual (último fechamento vs entrada)
    "max_return_pct": "float64",
    "pnl_usd": "float64",
    "value_usd": "float64",
    "action": "string",
    "reason": "string",             # regra que disparou a venda
    "signal_ts": "datetime64[ns, UTC]",  # dia em que a regra disparou
    "stop_price": "float64",        # abaixo disso: STOP (nulo se o STOP estiver desligado)
    "sell_below_price": "float64",  # SMA 200 atual: vender se fechar abaixo
    "above_sma_pct": "float64",     # quanto o último fechamento está acima (+) ou abaixo (−) da SMA 200
}


CLOSED_SCHEMA: dict[str, str] = {
    "position_id": "string",
    "symbol": "string",
    "entry_ts": "datetime64[ns, UTC]",
    "entry_price": "float64",
    "qty": "float64",
    "exit_ts": "datetime64[ns, UTC]",
    "exit_price": "float64",
    "return_pct": "float64",
    "pnl_usd": "float64",
}


def realized(closed: pd.DataFrame) -> pd.DataFrame:
    """Resultado das posições já vendidas, da venda mais recente para a mais antiga."""
    out = closed.assign(
        return_pct=(closed["exit_price"] / closed["entry_price"] - 1.0) * 100.0,
        pnl_usd=closed["qty"] * (closed["exit_price"] - closed["entry_price"]),
    )
    out = out[list(CLOSED_SCHEMA)].astype(CLOSED_SCHEMA)
    return out.sort_values("exit_ts", ascending=False, ignore_index=True)


def _against_rule(history: pd.DataFrame) -> pd.DataFrame:
    """Estado de hoje de cada moeda contra a regra: close, ts, sma_200, active, reason e since.

    `since` é o primeiro dia da sequência atual de fechamentos contra a regra (moeda abaixo da SMA 200
    ou BTC abaixo da dele).
    """
    h = history.sort_values(["symbol", "timestamp"])
    below = h["close"].lt(h["sma_200"])
    bad = below | ~h["regime_up"]
    last = h.groupby("symbol", sort=False).tail(1).set_index("symbol")
    last_below = below.groupby(h["symbol"], sort=False).tail(1).set_axis(last.index)
    last_good = h.loc[~bad].groupby("symbol", sort=False)["timestamp"].max()
    first_day = h.groupby("symbol", sort=False)["timestamp"].min()
    since = (last_good + pd.Timedelta(days=1)).reindex(first_day.index).fillna(first_day)
    return pd.DataFrame(
        {
            "last_ts": last["timestamp"],
            "last_close": last["close"],
            "sma_200": last["sma_200"],
            "active": ~last["regime_up"] | last_below,
            "reason": np.where(last_below, EXIT_TREND, EXIT_REGIME),
            "since": since.reindex(last.index),
        },
        index=last.index,
    )


def advise(positions: pd.DataFrame, history: pd.DataFrame, rules: ExitRules = ExitRules()) -> pd.DataFrame:
    """`positions`: position_id, symbol, entry_ts, entry_price, qty (apenas posições abertas)."""
    if positions.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in POSITION_SCHEMA.items()})

    base = positions[["position_id", "symbol", "entry_ts", "entry_price", "qty"]].reset_index(drop=True)
    base = base.astype({"symbol": "string"}).assign(entry_day=lambda p: p["entry_ts"].dt.floor("D"))

    # Caminho de cada posição: todos os fechamentos da moeda desde o dia da compra (o próprio dia conta).
    closes = history[["symbol", "timestamp", "close"]].astype({"symbol": "string"})
    path = base[["position_id", "symbol", "entry_day", "entry_price"]].merge(closes, on="symbol")
    path = path[path["timestamp"].ge(path["entry_day"])]
    ret = path["close"] / path["entry_price"] - 1.0
    peak = ret.groupby(path["position_id"]).max()
    if rules.stop_loss is None:
        stop_ts = pd.Series(pd.NaT, index=base["position_id"], dtype="datetime64[ns, UTC]")
    else:
        stop_ts = path.loc[ret.le(rules.stop_loss)].groupby("position_id")["timestamp"].min()

    state = _against_rule(history).reindex(base["symbol"].to_numpy()).set_axis(base.index)
    pos = base.join(state)
    stopped = pos["position_id"].map(stop_ts).notna()
    sell = (stopped | pos["active"].fillna(False)).astype(bool)
    since = pos["since"].where(pos["since"] > pos["entry_day"], pos["entry_day"])

    current = pos["last_close"] / pos["entry_price"] - 1.0
    stop_price = (
        pd.Series(np.nan, index=pos.index) if rules.stop_loss is None else pos["entry_price"] * (1.0 + rules.stop_loss)
    )
    out = pd.DataFrame(
        {
            "position_id": pos["position_id"],
            "symbol": pos["symbol"],
            "entry_ts": pos["entry_ts"],
            "entry_price": pos["entry_price"],
            "qty": pos["qty"],
            "last_ts": pos["last_ts"],
            "last_close": pos["last_close"],
            "return_pct": current * 100.0,
            "max_return_pct": pos["position_id"].map(peak) * 100.0,
            "pnl_usd": pos["qty"] * (pos["last_close"] - pos["entry_price"]),
            "value_usd": pos["qty"] * pos["last_close"],
            "action": np.where(sell, ACTION_SELL, ACTION_HOLD),
            "reason": pd.Series(np.where(stopped, EXIT_STOP, pos["reason"]), index=pos.index).where(sell),
            "signal_ts": pd.Series(np.where(stopped, pos["position_id"].map(stop_ts), since), index=pos.index).where(sell),
            "stop_price": stop_price,
            "sell_below_price": pos["sma_200"],
            "above_sma_pct": (pos["last_close"] / pos["sma_200"] - 1.0) * 100.0,
        }
    )
    out = out[list(POSITION_SCHEMA)].astype(POSITION_SCHEMA)
    return out.sort_values(["action", "return_pct"], ascending=[False, True], ignore_index=True)
