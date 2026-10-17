"""Recomendação para posições reais: VENDER (com motivo e desde quando) ou SEGURAR.

Usa as mesmas regras de saída do backtest (`trade_simulator`): vender ao fechar abaixo da SMA 200
da moeda, ou quando o BTC fecha abaixo da dele, ou na perda de 20% sobre o preço pago.

O STOP é permanente: uma vez atingido, a posição segue como VENDER. As saídas por tendência e por
mercado valem pelo estado de hoje: se a moeda voltou a fechar acima da SMA 200 (e o BTC também), a
posição volta a SEGURAR; `signal_ts` é o primeiro dia da sequência atual de fechamentos contra a regra
(ou o dia da compra, se for mais recente).

Moeda sem dado confiável hoje (`available`, de `data_quality.availability`) fica INDISPONÍVEL, a menos
que o STOP já tenha disparado (fato do passado). Puro (CLAUDE.md §1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config

from .exit_rules import STATE_SELL, STATE_WATCH, ExitParams, position_state
from .trade_simulator import EXIT_REGIME, EXIT_STOP, EXIT_TREND, STOP_TOLERANCE, ExitRules

ACTION_SELL = "VENDER"
ACTION_HOLD = "SEGURAR"
ACTION_WATCH = "ATENÇÃO"   # nenhuma regra disparou, mas alguma está a metade do caminho (docs/exit_rules.md)
ACTION_UNAVAILABLE = "INDISPONÍVEL"  # sem dado confiável hoje: nem vender nem segurar com base em dado velho

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
    "data_note": "string",          # motivo do INDISPONÍVEL; nulo nos demais casos
    "state_rule": "string",         # regra que disparou (VENDER) ou que chamou atenção (ATENÇÃO)
    "state_detail": "string",       # a explicação em uma frase, com os números de hoje
    "rule_evidence": "string",      # o que essa regra fez no histórico (disparos, queda depois da venda)
    "drawdown_entry_pct": "float64",  # pior ponto desde a entrada, sobre o preço pago (0 ou negativo)
    "drawdown_peak_pct": "float64",   # queda do fechamento atual desde o maior fechamento depois da entrada
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


def advise(
    positions: pd.DataFrame,
    history: pd.DataFrame,
    rules: ExitRules = ExitRules(),
    available: pd.DataFrame | None = None,
    rule_table: pd.DataFrame | None = None,
    trailing: float | None = None,
) -> pd.DataFrame:
    """`positions`: position_id, symbol, entry_ts, entry_price, qty (apenas posições abertas).

    `rule_table`: `evidence/exit_rules.parquet` (o que cada regra fez no backtest), usado no texto `rule_evidence`.
    `trailing`: queda desde o topo que dispara VENDER; None (padrão, nenhum valor foi adotado no backtest) = só ATENÇÃO.

    `available`: saída de `data_quality.availability` (symbol, available, reason); None = tudo disponível.
    """
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
        stop_ts = path.loc[ret.le(rules.stop_loss + STOP_TOLERANCE)].groupby("position_id")["timestamp"].min()

    state = _against_rule(history).reindex(base["symbol"].to_numpy()).set_axis(base.index)
    pos = base.join(state)
    stop_at = pd.Series(stop_ts.reindex(pos["position_id"]).to_numpy(), index=pos.index)  # NaT se não houve STOP
    stopped = stop_at.notna()
    sell = (stopped | pos["active"].fillna(False)).astype(bool)
    note = (
        pd.Series(pd.NA, index=pos.index, dtype="string")
        if available is None
        else pos["symbol"].map(available.set_index("symbol")["reason"]).astype("string")
    )
    ok = pd.Series(True, index=pos.index) if available is None else pos["symbol"].map(available.set_index("symbol")["available"]).fillna(True).astype(bool)
    blocked = ~ok & ~stopped
    sell = sell & ~blocked
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
            "action": np.select([blocked, sell], [ACTION_UNAVAILABLE, ACTION_SELL], ACTION_HOLD),
            "reason": pd.Series(np.where(stopped, EXIT_STOP, pos["reason"]), index=pos.index).where(sell),
            "signal_ts": pd.Series(np.where(stopped, stop_at, since), index=pos.index).where(sell),
            "stop_price": stop_price,
            "sell_below_price": pos["sma_200"],
            "above_sma_pct": (pos["last_close"] / pos["sma_200"] - 1.0) * 100.0,
            "data_note": note.where(blocked),
        }
    )
    out = _with_states(out, path, history, rules, trailing, rule_table, blocked)
    out = out[list(POSITION_SCHEMA)].astype(POSITION_SCHEMA)
    return out.sort_values(["action", "return_pct"], ascending=[False, True], ignore_index=True)


def rule_evidence_text(rule: str | None, table: pd.DataFrame | None) -> str | None:
    """Uma frase com o que a regra fez no backtest (disparos, retorno médio, o que o preço fez 30 dias depois da venda)."""
    if rule is None or table is None or table.empty:
        return None
    row = table[table["rule"].eq(rule)]
    if row.empty:
        return None
    r = row.iloc[0]
    n = int(r["n"]) if pd.notna(r["n"]) else 0
    parts = [f"{rule}: {n} disparos no backtest"]
    if pd.notna(r["share_fell_after"]):
        parts.append(f"em {float(r['share_fell_after']):.0%} o preço caiu nos 30 dias seguintes à venda")
    if pd.notna(r["mean_return"]):
        parts.append(f"retorno médio da operação {float(r['mean_return']):+.1%}")
    if not bool(r["adopted"]):
        parts.append("regra não adotada: só aviso")
    return "; ".join(parts)


def _with_states(
    out: pd.DataFrame,
    path: pd.DataFrame,
    history: pd.DataFrame,
    rules: ExitRules,
    trailing: float | None,
    rule_table: pd.DataFrame | None,
    blocked: "pd.Series[bool]",
) -> pd.DataFrame:
    """Acrescenta SEGURAR / ATENÇÃO / VENDER com a regra, os drawdowns e a evidência histórica da regra."""
    params = ExitParams(stop=None if rules.stop_loss is None else -rules.stop_loss, trailing=trailing)
    btc = history[history["symbol"].eq(config.REGIME_SYMBOL)].sort_values("timestamp")
    btc_close = float(btc["close"].iloc[-1]) if not btc.empty else float("nan")
    btc_sma = float(btc["sma_200"].iloc[-1]) if not btc.empty else float("nan")
    paths = {str(k): g.sort_values("timestamp")["close"].to_numpy(dtype="float64") for k, g in path.groupby("position_id")}
    blocked_by_id = dict(zip(out["position_id"], blocked.reindex(out.index).fillna(False).astype(bool), strict=False))
    actions: list[str] = []
    rules_out: list[str | None] = []
    details: list[str] = []
    evidence: list[str | None] = []
    dd_entry: list[float] = []
    dd_peak: list[float] = []

    def num(value: object) -> float:
        return float(value) if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value) else float("nan")

    for r in out.to_dict("records"):
        last = num(r["last_close"])
        closes = paths.get(str(r["position_id"]), np.array([last]))
        closes = closes[np.isfinite(closes)] if len(closes) else np.array([last])
        entry = num(r["entry_price"])
        peak = max(float(closes.max()), entry)
        dd_entry.append(min(float(closes.min()) / entry - 1.0, 0.0) * 100.0)
        dd_peak.append((last / peak - 1.0) * 100.0 if np.isfinite(last) else float("nan"))
        if r["action"] == ACTION_UNAVAILABLE and blocked_by_id.get(r["position_id"], False):
            actions.append(ACTION_UNAVAILABLE)
            rules_out.append(None)
            details.append(str(r["data_note"]) if pd.notna(r["data_note"]) else "sem dado confiável hoje")
            evidence.append(None)
            continue
        st = position_state(
            entry_price=entry, closes_since_entry=closes.tolist(), sma=num(r["sell_below_price"]),
            btc_close=btc_close, btc_sma=btc_sma, params=params,
        )
        sell = r["action"] == ACTION_SELL or st.state == STATE_SELL
        state = ACTION_SELL if sell else (ACTION_WATCH if st.state == STATE_WATCH else ACTION_HOLD)
        rule = (str(r["reason"]) if pd.notna(r["reason"]) else st.rule) if sell else st.rule
        actions.append(state)
        rules_out.append(rule)
        details.append(st.detail if st.state == STATE_SELL or not sell else f"regra {rule} ativa")
        evidence.append(rule_evidence_text(rule, rule_table))
    return out.assign(
        action=pd.Series(actions, index=out.index),
        state_rule=pd.Series(rules_out, index=out.index, dtype="string"),
        state_detail=pd.Series(details, index=out.index, dtype="string"),
        rule_evidence=pd.Series(evidence, index=out.index, dtype="string"),
        drawdown_entry_pct=pd.Series(dd_entry, index=out.index),
        drawdown_peak_pct=pd.Series(dd_peak, index=out.index),
    )
