"""Histórico diário do estado das posições abertas e detecção de mudança de estado (para o aviso só na mudança).

Puro (CLAUDE.md §1). O histórico é append-only: uma linha por posição e dia de dados, nunca reescrita. Uma linha tem
`changed = True` quando o estado (SEGURAR, ATENÇÃO, VENDER) difere do último estado conhecido da mesma posição; a primeira
linha de uma posição só conta como mudança se já nasce fora de SEGURAR. INDISPONÍVEL (sem dado confiável) não é um estado
de decisão: nunca gera aviso e não conta como "último estado". O Telegram avisa as mudanças ainda não enviadas
(`pending_changes`), então nada se repete todo dia e uma falha de envio é reenviada na execução seguinte.
"""

from __future__ import annotations

import pandas as pd

from .position_advisor import ACTION_HOLD, ACTION_UNAVAILABLE

POSITION_STATE_LOG_SCHEMA: dict[str, str] = {
    "day": "datetime64[ns, UTC]",
    "position_id": "string",
    "symbol": "string",
    "state": "string",
    "prev_state": "string",
    "rule": "string",
    "detail": "string",
    "return_pct": "float64",
    "drawdown_entry_pct": "float64",
    "drawdown_peak_pct": "float64",
    "last_close": "float64",
    "changed": "bool",
    "rule_evidence": "string",
}

NOTIFICATIONS_SCHEMA: dict[str, str] = {
    "day": "datetime64[ns, UTC]",
    "position_id": "string",
    "state": "string",
    "sent_at": "datetime64[ns, UTC]",
}


def empty_state_log() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in POSITION_STATE_LOG_SCHEMA.items()})


def empty_notifications() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in NOTIFICATIONS_SCHEMA.items()})


def new_state_rows(positions: pd.DataFrame, log: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """Linhas de `day` para as posições abertas (`advise`), sem repetir (dia, posição) que já existe no histórico."""
    if positions.empty:
        return empty_state_log()
    done = set(log.loc[log["day"].eq(day), "position_id"]) if not log.empty else set()
    decided = log[log["state"].ne(ACTION_UNAVAILABLE) & log["day"].lt(day)] if not log.empty else log
    last_state = decided.sort_values("day").groupby("position_id")["state"].last() if not decided.empty else pd.Series(dtype="string")
    rows = []
    for r in positions.to_dict("records"):
        pid = str(r["position_id"])
        if pid in done:
            continue
        state = str(r["action"])
        prev = last_state.get(pid)
        prev_state = None if prev is None or pd.isna(prev) else str(prev)
        if state == ACTION_UNAVAILABLE:
            changed = False
        elif prev_state is None:
            changed = state != ACTION_HOLD
        else:
            changed = state != prev_state
        rows.append(
            {"day": day, "position_id": pid, "symbol": r["symbol"], "state": state, "prev_state": prev_state,
             "rule": r["state_rule"], "detail": r["state_detail"], "return_pct": r["return_pct"],
             "drawdown_entry_pct": r["drawdown_entry_pct"], "drawdown_peak_pct": r["drawdown_peak_pct"],
             "last_close": r["last_close"], "changed": changed, "rule_evidence": r["rule_evidence"]}
        )
    if not rows:
        return empty_state_log()
    return pd.DataFrame(rows).astype(POSITION_STATE_LOG_SCHEMA)


def pending_changes(log: pd.DataFrame, notifications: pd.DataFrame) -> pd.DataFrame:
    """Mudanças de estado ainda não avisadas, da mais antiga para a mais nova."""
    if log.empty:
        return empty_state_log()
    changes = log[log["changed"]]
    if notifications.empty:
        return changes.sort_values(["day", "position_id"], ignore_index=True)
    sent = set(zip(notifications["day"], notifications["position_id"], notifications["state"], strict=True))
    keep = [(d, p, s) not in sent for d, p, s in zip(changes["day"], changes["position_id"], changes["state"], strict=True)]
    return changes[keep].sort_values(["day", "position_id"], ignore_index=True)


def acknowledgements(changes: pd.DataFrame, sent_at: pd.Timestamp) -> pd.DataFrame:
    """Linhas do registro de avisos enviados para `changes`."""
    if changes.empty:
        return empty_notifications()
    out = changes[["day", "position_id", "state"]].assign(sent_at=sent_at)
    return out.astype(NOTIFICATIONS_SCHEMA).reset_index(drop=True)
