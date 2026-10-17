"""Regras de saída das posições: simulação das operações, relatório por regra e comparação do trailing.

Puro (CLAUDE.md §1). Protocolo fixado antes dos resultados em `docs/exit_rules.md`. Cada regra decide no FECHAMENTO do dia
`d` e a venda é simulada no fechamento seguinte, com os custos por lado de `config.py` (já calculados em `Prepared.cost`).

Regras: STOP (perda sobre a entrada), TENDENCIA (fechou abaixo da SMA 200 da moeda), MERCADO (BTC abaixo da SMA 200 dele)
e TRAILING (queda desde o maior fechamento depois da entrada).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config
from .signal_validation import REGIME_SYMBOL, Prepared, stable_seed
from .stats import block_indices, holm_adjust

EXIT_STOP = "STOP"
EXIT_TREND = "TENDENCIA"
EXIT_MARKET = "MERCADO"
EXIT_TRAILING = "TRAILING"
EXIT_OPEN = "ABERTA"          # nenhuma regra disparou até o fim do período
EXIT_DATA_END = "FIM_DOS_DADOS"  # a moeda parou de negociar
RULE_PRIORITY: tuple[str, ...] = (EXIT_STOP, EXIT_TRAILING, EXIT_TREND, EXIT_MARKET)

TRAILING_GRID: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
STOP_LOSS = 0.20
STOP_TOLERANCE = 1e-9
POST_EXIT_DAYS = 30
ATTENTION_STOP_FRACTION = 0.5
ATTENTION_SMA_DISTANCE = 0.03
ATTENTION_TRAILING_X = 0.20
"""Estados de ATENÇÃO fixados a priori (docs/exit_rules.md): metade do caminho até a regra disparar."""

TRADE_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "signal_ts": "datetime64[ns, UTC]",
    "entry_ts": "datetime64[ns, UTC]",
    "exit_ts": "datetime64[ns, UTC]",
    "reason": "string",
    "net_return": "float64",     # líquido de custos nos dois lados
    "hold_days": "int64",
    "peak_return": "float64",    # maior retorno bruto antes da saída
    "post_exit_30d": "float64",  # do preço de venda ao fechamento 30 dias depois (NaN se não existe)
    "is_open": "bool",
}


@dataclass(frozen=True)
class ExitParams:
    stop: float | None = STOP_LOSS
    trend: bool = True
    market: bool = True
    trailing: float | None = None

    def label(self) -> str:
        parts = [r for r, on in ((EXIT_STOP, self.stop is not None), (EXIT_TREND, self.trend), (EXIT_MARKET, self.market)) if on]
        if self.trailing is not None:
            parts.append(f"{EXIT_TRAILING}({self.trailing:.0%})")
        return "+".join(parts) or "NENHUMA"


def _trigger_day(
    p: np.ndarray, sma: np.ndarray, btc: np.ndarray, btc_sma: np.ndarray, params: ExitParams
) -> tuple[int, str] | None:
    """Primeiro índice (relativo ao caminho, depois da entrada) em que alguma regra dispara, e qual (prioridade em empate).
    `p[0]` é o preço de entrada."""
    n = len(p)
    if n < 2:
        return None
    hits: dict[str, np.ndarray] = {}
    if params.stop is not None:
        hits[EXIT_STOP] = (p / p[0] - 1.0) <= -params.stop + STOP_TOLERANCE
    if params.trailing is not None:
        hits[EXIT_TRAILING] = p <= np.maximum.accumulate(p) * (1.0 - params.trailing)
    if params.trend:
        hits[EXIT_TREND] = p < sma
    if params.market:
        hits[EXIT_MARKET] = btc < btc_sma
    first = n
    reason = ""
    for name in RULE_PRIORITY:
        h = hits.get(name)
        if h is None:
            continue
        h = h.copy()
        h[0] = False  # o dia da entrada não dispara a própria saída
        idx = np.flatnonzero(h)
        if len(idx) and int(idx[0]) < first:
            first, reason = int(idx[0]), name
    return (first, reason) if first < n else None


def simulate_trades(
    prep: Prepared, params: ExitParams, *, entries_from: pd.Timestamp | None, entries_to: pd.Timestamp, data_end: pd.Timestamp
) -> pd.DataFrame:
    """Operações de cada sinal COMPRAR (`prep.events`): entrada no fechamento seguinte ao sinal, saída pela primeira regra
    de `params` (executada no fechamento seguinte). Sinais com entrada em [`entries_from`, `entries_to`]; a operação ainda
    aberta é encerrada no último fechamento até `data_end` (marcada `is_open`)."""
    if prep.priced is None or prep.sma is None or prep.cost is None or prep.last_candle is None:
        raise ValueError("Prepared sem os quadros de preço (use signal_validation.prepare)")
    priced, sma, cost = prep.priced, prep.sma, prep.cost
    index = priced.index
    btc_p = priced[REGIME_SYMBOL].to_numpy(dtype="float64")
    btc_s = sma[REGIME_SYMBOL].to_numpy(dtype="float64")
    end_pos = int(index.searchsorted(data_end, side="right")) - 1
    rows: list[dict[str, object]] = []
    for symbol in prep.events.columns:
        ev = np.flatnonzero(prep.events[symbol].to_numpy())
        if len(ev) == 0:
            continue
        px = priced[symbol].to_numpy(dtype="float64")
        sm = sma[symbol].to_numpy(dtype="float64")
        cs = cost[symbol].to_numpy(dtype="float64")
        last_ts = prep.last_candle[symbol]
        last_pos = int(index.searchsorted(last_ts)) if pd.notna(last_ts) else -1
        ended = last_pos < len(index) - 1 - config.LONG_STALE_DAYS  # parou de negociar (deslistada)
        for i in ev:
            e = int(i) + 1
            entry_ts = index[e] if e < len(index) else None
            if entry_ts is None or not np.isfinite(px[e]) or e > last_pos:
                continue
            if (entries_from is not None and entry_ts < entries_from) or entry_ts > entries_to:
                continue
            limit = min(end_pos, last_pos)
            if limit <= e:
                continue
            path = slice(e, limit + 1)
            hit = _trigger_day(px[path], sm[path], btc_p[path], btc_s[path], params)
            if hit is None:
                x_pos = limit
                reason = EXIT_DATA_END if ended and limit == last_pos else EXIT_OPEN
                is_open = reason == EXIT_OPEN
            else:
                d = e + hit[0]
                x_pos, reason, is_open = min(d + 1, limit), hit[1], False
            c_in, c_out = float(cs[e]) if np.isfinite(cs[e]) else 0.0, float(cs[x_pos]) if np.isfinite(cs[x_pos]) else 0.0
            net = (1.0 - c_in) * (1.0 - c_out) * px[x_pos] / px[e] - 1.0
            after = x_pos + POST_EXIT_DAYS
            post = float(px[after] / px[x_pos] - 1.0) if after <= min(last_pos, len(index) - 1) and np.isfinite(px[after]) else float("nan")
            rows.append(
                {"symbol": symbol, "signal_ts": index[int(i)], "entry_ts": entry_ts, "exit_ts": index[x_pos], "reason": reason,
                 "net_return": float(net), "hold_days": int(x_pos - e), "peak_return": float(np.nanmax(px[e:x_pos + 1]) / px[e] - 1.0),
                 "post_exit_30d": post, "is_open": is_open}
            )
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in TRADE_SCHEMA.items()})
    out = pd.DataFrame(rows).astype(TRADE_SCHEMA)
    return out.sort_values(["signal_ts", "symbol"], ignore_index=True)


RULE_REPORT_SCHEMA: dict[str, str] = {
    "rule": "string",
    "n": "int64",
    "mean_return": "float64",
    "median_return": "float64",
    "mean_post_exit_30d": "float64",
    "share_fell_after": "float64",   # fração dos disparos em que o preço caiu nos 30 dias seguintes à venda
    "mean_hold_days": "float64",
}


def rule_report(trades: pd.DataFrame) -> pd.DataFrame:
    """Por regra que encerrou as operações: quantas vezes disparou, o que rendeu e o que o preço fez depois da venda."""
    rows = []
    for rule, g in trades.groupby("reason", observed=True):
        post = g["post_exit_30d"].dropna()
        rows.append(
            {"rule": str(rule), "n": len(g), "mean_return": float(g["net_return"].mean()), "median_return": float(g["net_return"].median()),
             "mean_post_exit_30d": float(post.mean()) if len(post) else float("nan"),
             "share_fell_after": float((post < 0).mean()) if len(post) else float("nan"), "mean_hold_days": float(g["hold_days"].mean())}
        )
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in RULE_REPORT_SCHEMA.items()})
    return pd.DataFrame(rows).astype(RULE_REPORT_SCHEMA).sort_values("n", ascending=False, ignore_index=True)


TRAILING_SCHEMA: dict[str, str] = {
    "x": "float64",
    "n": "int64",
    "mean_base": "float64",
    "mean_trailing": "float64",
    "mean_diff": "float64",
    "ci_low": "float64",
    "ci_high": "float64",
    "p_value": "float64",
    "p_holm": "float64",
    "fired_share": "float64",   # fração das operações encerradas pelo trailing
}


def paired_diff_stats(diff: np.ndarray, seed: int, resamples: int) -> tuple[float, float, float, float]:
    """(média, IC95 baixo, IC95 alto, valor-p unilateral de melhora) da diferença pareada, por bootstrap em blocos."""
    n = len(diff)
    if n < 2:
        nan = float("nan")
        return (float(diff.mean()) if n else nan, nan, nan, nan)
    rng = np.random.default_rng(seed)
    block = max(1, math.ceil(n ** (1.0 / 3.0)))
    mean = float(diff.mean())
    boot = diff[block_indices(n, block, resamples, rng)].mean(axis=1)
    null = (diff - mean)[block_indices(n, block, resamples, rng)].mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    p = (1.0 + float(np.sum(null >= mean))) / (resamples + 1.0)
    return mean, float(lo), float(hi), p


def compare_trailing(
    base: pd.DataFrame, variants: dict[float, pd.DataFrame], seed: int = config.VALIDATION_SEED,
    resamples: int = config.VALIDATION_BOOTSTRAP_RESAMPLES,
) -> pd.DataFrame:
    """Cada trailing contra a referência (mesmas operações, diferença pareada do retorno líquido), com Holm na grade."""
    rows = []
    key = ["symbol", "signal_ts"]
    for x, trades in variants.items():
        joined = base.merge(trades, on=key, suffixes=("_b", "_t")).sort_values("signal_ts")
        diff = (joined["net_return_t"] - joined["net_return_b"]).to_numpy(dtype="float64")
        mean, lo, hi, p = paired_diff_stats(diff, int(stable_seed(seed, "trailing", x)), resamples)
        rows.append(
            {"x": x, "n": len(joined), "mean_base": float(joined["net_return_b"].mean()) if len(joined) else float("nan"),
             "mean_trailing": float(joined["net_return_t"].mean()) if len(joined) else float("nan"), "mean_diff": mean,
             "ci_low": lo, "ci_high": hi, "p_value": p, "p_holm": float("nan"),
             "fired_share": float((trades["reason"] == EXIT_TRAILING).mean()) if len(trades) else float("nan")}
        )
    out = pd.DataFrame(rows)
    out["p_holm"] = holm_adjust(out["p_value"].tolist())
    return out.astype(TRAILING_SCHEMA)


def adopted_trailing(grid: pd.DataFrame, alpha: float = config.VALIDATION_ALPHA) -> float | None:
    """O `x` de menor p ajustado, só se p_holm < alpha e o limite inferior do IC > 0. Senão, nenhum (None)."""
    ok = grid[grid["p_holm"].lt(alpha) & grid["ci_low"].gt(0)]
    if ok.empty:
        return None
    return float(ok.sort_values(["p_holm", "x"]).iloc[0]["x"])


def holdout_vetoes(base: pd.DataFrame, trailing: pd.DataFrame, min_trades: int = 20) -> bool:
    """O teste final só pode revogar: com pelo menos `min_trades` operações e diferença média negativa."""
    joined = base.merge(trailing, on=["symbol", "signal_ts"], suffixes=("_b", "_t"))
    if len(joined) < min_trades:
        return False
    return bool((joined["net_return_t"] - joined["net_return_b"]).mean() < 0)


# ---------------------------------------------------------------------------------------------
# Estado de uma posição aberta
# ---------------------------------------------------------------------------------------------

STATE_HOLD = "SEGURAR"
STATE_WATCH = "ATENÇÃO"
STATE_SELL = "VENDER"
STATES: tuple[str, ...] = (STATE_HOLD, STATE_WATCH, STATE_SELL)


@dataclass(frozen=True)
class PositionState:
    state: str
    rule: str | None          # regra que disparou (VENDER) ou que chamou atenção (ATENÇÃO)
    detail: str


def position_state(
    *, entry_price: float, closes_since_entry: Sequence[float], sma: float, btc_close: float, btc_sma: float, params: ExitParams
) -> PositionState:
    """Estado de HOJE de uma posição, só com dados até o último fechamento (`closes_since_entry` inclui o dia da compra).
    Regras na prioridade STOP, TRAILING, TENDENCIA, MERCADO. VENDER se alguma disparou; ATENÇÃO se alguma está a metade do
    caminho (docs/exit_rules.md); senão SEGURAR."""
    closes = np.asarray(closes_since_entry, dtype="float64")
    last = float(closes[-1])
    ret = last / entry_price - 1.0
    peak = float(max(closes.max(), entry_price))
    drawdown_from_peak = last / peak - 1.0
    worst = float(closes.min()) / entry_price - 1.0
    if params.stop is not None and worst <= -params.stop + STOP_TOLERANCE:  # o STOP é permanente: uma vez atingido, vale
        return PositionState(STATE_SELL, EXIT_STOP, f"chegou a {worst:.1%} sobre a entrada (limite -{params.stop:.0%})")
    if params.trailing is not None and drawdown_from_peak <= -params.trailing + STOP_TOLERANCE:
        return PositionState(STATE_SELL, EXIT_TRAILING, f"queda de {drawdown_from_peak:.1%} desde o topo (limite -{params.trailing:.0%})")
    if params.trend and np.isfinite(sma) and last < sma:
        return PositionState(STATE_SELL, EXIT_TREND, "fechou abaixo da SMA 200 da moeda")
    if params.market and np.isfinite(btc_sma) and btc_close < btc_sma:
        return PositionState(STATE_SELL, EXIT_MARKET, "o Bitcoin fechou abaixo da SMA 200")
    if params.stop is not None and ret <= -params.stop * ATTENTION_STOP_FRACTION + STOP_TOLERANCE:
        return PositionState(STATE_WATCH, EXIT_STOP, f"perda de {ret:.1%}, metade do caminho até o stop de -{params.stop:.0%}")
    x = params.trailing if params.trailing is not None else ATTENTION_TRAILING_X
    if drawdown_from_peak <= -x * ATTENTION_STOP_FRACTION + STOP_TOLERANCE:
        return PositionState(STATE_WATCH, EXIT_TRAILING, f"queda de {drawdown_from_peak:.1%} desde o topo")
    if params.trend and np.isfinite(sma) and last / sma - 1.0 <= ATTENTION_SMA_DISTANCE:
        return PositionState(STATE_WATCH, EXIT_TREND, f"a {last / sma - 1.0:.1%} acima da SMA 200")
    if params.market and np.isfinite(btc_sma) and btc_close / btc_sma - 1.0 <= ATTENTION_SMA_DISTANCE:
        return PositionState(STATE_WATCH, EXIT_MARKET, f"o Bitcoin está a {btc_close / btc_sma - 1.0:.1%} acima da SMA 200")
    return PositionState(STATE_HOLD, None, "nenhuma regra perto de disparar")
