"""Recomendação para posições reais: VENDER (com motivo e desde quando) ou SEGURAR.

Usa exatamente as regras de saída do backtest (`trade_simulator`), então o histórico mostra como
essa mesma recomendação teria se saído no passado. Puro (CLAUDE.md §1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .trade_simulator import STATUS_CLOSED, ExitRules, simulate

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
    "stop_price": "float64",        # abaixo disso: STOP
    "trail_price": "float64",       # abaixo disso: PROTEGER LUCRO (só depois de +15%)
    "target_price": "float64",      # SMA 90 atual: ALVO
    "zscore_90": "float64",
    "rsi_14": "float64",
}


def advise(positions: pd.DataFrame, history: pd.DataFrame, rules: ExitRules = ExitRules()) -> pd.DataFrame:
    """`positions`: position_id, symbol, entry_ts, entry_price, qty (apenas posições abertas)."""
    if positions.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in POSITION_SCHEMA.items()})

    base = positions[["position_id", "symbol", "entry_ts", "entry_price", "qty"]]
    entries = base.rename(columns={"position_id": "trade_id"}).assign(
        entry_ts=lambda p: p["entry_ts"].dt.floor("D")
    )[["trade_id", "symbol", "entry_ts", "entry_price"]]
    sim = simulate(entries, history, rules, include_entry_day=True).set_index("trade_id")
    pos = base.set_index("position_id").join(sim.drop(columns=["symbol", "entry_ts", "entry_price"]))

    current = pos["last_close"] / pos["entry_price"] - 1.0
    peak = pos["max_return_pct"] / 100.0
    trail_active = peak.ge(rules.trail_activation)
    sell = pos["status"].eq(STATUS_CLOSED).fillna(False).astype(bool)

    out = pd.DataFrame(
        {
            "position_id": pos.index.astype("string"),
            "symbol": pos["symbol"],
            "entry_ts": pos["entry_ts"],
            "entry_price": pos["entry_price"],
            "qty": pos["qty"],
            "last_ts": pos["last_ts"],
            "last_close": pos["last_close"],
            "return_pct": current * 100.0,
            "max_return_pct": pos["max_return_pct"],
            "pnl_usd": pos["qty"] * (pos["last_close"] - pos["entry_price"]),
            "value_usd": pos["qty"] * pos["last_close"],
            "action": np.where(sell, ACTION_SELL, ACTION_HOLD),
            "reason": pos["exit_reason"].where(sell),
            "signal_ts": pos["exit_ts"].where(sell),
            "stop_price": pos["entry_price"] * (1.0 + rules.stop_loss),
            "trail_price": (pos["entry_price"] * (1.0 + peak) * (1.0 - rules.trail_drawdown)).where(trail_active),
            "target_price": pos["sma_90"],
            "zscore_90": pos["zscore_90"],
            "rsi_14": pos["rsi_14"],
        }
    )
    out = out[list(POSITION_SCHEMA)].astype(POSITION_SCHEMA)
    return out.sort_values(["action", "return_pct"], ascending=[False, True], ignore_index=True)
