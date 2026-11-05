"""Estudo do "fundo confirmado por 2 candles": regra, operações, comparador do acaso e inferência.

Protocolo: docs/fundo_confirmado.md (fixado antes dos resultados). Tudo aqui é função pura: sem rede, disco ou relógio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from src.transformers.multiple_testing import holm

COST_ROUND_TRIP = 0.002
CONFIRM_DAYS = 2
ENTRY_DELAY = CONFIRM_DAYS + 1  # a regra só é conhecida no fechamento de t+2; compra na abertura de t+3
LOOKBACKS: tuple[int, ...] = (10, 20, 50)
HOLDS: tuple[int, ...] = (5, 10, 20)
BLOCK_DAYS = 30
RESAMPLES = 2000
SEED = 20261105
CI_LEVEL = 0.90
MIN_TRADES = 30
SPLIT = pd.Timestamp("2023-01-01", tz="UTC")

PERIOD_DEV = "DESENVOLVIMENTO"
PERIOD_TEST = "TESTE_FINAL"
ENTRY_HONEST = "HONESTA"
ENTRY_BIASED = "COM_VIES"
STATUS_WORKS = "FUNCIONA"
STATUS_NOT_SHOWN = "NAO_DEMONSTRADO"
STATUS_FEW = "DADOS_INSUFICIENTES"

Floats = NDArray[np.float64]

TRADE_COLUMNS = [
    "symbol", "lookback", "hold", "signal_date", "entry_date", "exit_date", "period",
    "ret_honest", "ret_biased", "ret_random",
]
RESULT_COLUMNS = [
    "lookback", "hold", "entry", "period", "n_trades", "mean_return", "mean_random", "mean_excess",
    "ci_low", "ci_high", "p_value", "p_holm", "status",
]


@dataclass(frozen=True)
class BottomRule:
    lookback: int
    hold: int

    def __post_init__(self) -> None:
        if self.lookback < 2 or self.hold < 1:
            raise ValueError("lookback >= 2 e hold >= 1")


def bottom_signal_days(close: Floats, lookback: int) -> NDArray[np.bool_]:
    """True no dia `t` em que o fechamento é o menor dos últimos `lookback` e os 2 fechamentos seguintes sobem.

    O sinal em `t` usa `close[t+1]` e `close[t+2]`: só é conhecido no fechamento de `t+2`.
    """
    n = close.size
    out = np.zeros(n, dtype=np.bool_)
    if n < lookback + CONFIRM_DAYS:
        return out
    is_low = (close <= pd.Series(close).rolling(lookback).min().to_numpy()) & (np.arange(n) >= lookback - 1)
    up = np.zeros(n, dtype=np.bool_)  # up[i]: o fechamento de i+1 é maior que o de i
    up[: n - 1] = close[1:] > close[:-1]
    nxt = np.zeros(n, dtype=np.bool_)
    nxt[: n - 1] = up[1:]
    return np.asarray(is_low & up & nxt, dtype=np.bool_)


def _random_returns(open_: Floats, hold: int, cost: float) -> Floats:
    """Retorno líquido de entrar na abertura de `d` e sair na abertura de `d+hold` (NaN sem saída)."""
    n = open_.size
    out = np.full(n, np.nan, dtype=np.float64)
    if n > hold:
        out[: n - hold] = open_[hold:] / open_[: n - hold] - 1.0 - cost
    return out


def coin_trades(frame: pd.DataFrame, rule: BottomRule, cost: float = COST_ROUND_TRIP,
                split: pd.Timestamp = SPLIT) -> pd.DataFrame:
    """Operações de uma moeda (colunas `timestamp`, `open`, `close`, `symbol`), sem sobreposição.

    `ret_honest`: compra na abertura de t+3. `ret_biased`: compra no fechamento de t (olhando o futuro). As duas saem na
    abertura de t+3+hold. `ret_random`: média do retorno de entrar em qualquer dia da moeda, no mesmo período.
    """
    data = frame.sort_values("timestamp").reset_index(drop=True)
    close = data["close"].to_numpy(dtype="float64")
    open_ = data["open"].to_numpy(dtype="float64")
    stamps = data["timestamp"]
    n = close.size
    signals = np.flatnonzero(bottom_signal_days(close, rule.lookback))
    random_ret = _random_returns(open_, rule.hold, cost)
    entry_period = np.where((stamps < split).to_numpy(), PERIOD_DEV, PERIOD_TEST)
    base_by_period = {
        p: float(np.nanmean(random_ret[(entry_period == p) & np.isfinite(random_ret)]))
        for p in (PERIOD_DEV, PERIOD_TEST)
        if bool(((entry_period == p) & np.isfinite(random_ret)).any())
    }
    rows: list[dict[str, object]] = []
    last_exit = -1
    for t in signals:
        entry = int(t) + ENTRY_DELAY
        exit_ = entry + rule.hold
        if exit_ >= n or entry <= last_exit:
            continue
        period = str(entry_period[entry])
        rows.append({
            "symbol": str(data["symbol"].iloc[0]), "lookback": rule.lookback, "hold": rule.hold,
            "signal_date": stamps.iloc[int(t)], "entry_date": stamps.iloc[entry], "exit_date": stamps.iloc[exit_],
            "period": period,
            "ret_honest": float(open_[exit_] / open_[entry] - 1.0 - cost),
            "ret_biased": float(open_[exit_] / close[int(t)] - 1.0 - cost),
            "ret_random": base_by_period.get(period, float("nan")),
        })
        last_exit = exit_
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def all_trades(candles: pd.DataFrame, rules: list[BottomRule] | None = None, cost: float = COST_ROUND_TRIP,
               split: pd.Timestamp = SPLIT) -> pd.DataFrame:
    """Operações de todas as moedas e configurações."""
    chosen = rules if rules is not None else [BottomRule(n, h) for n in LOOKBACKS for h in HOLDS]
    parts = [
        coin_trades(group, rule, cost, split)
        for rule in chosen
        for _, group in candles.groupby("symbol", sort=True)
    ]
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    return pd.concat(parts, ignore_index=True)


def block_bootstrap_mean(values: Floats, entry_days: NDArray[np.int64], *, resamples: int = RESAMPLES,
                         block_days: int = BLOCK_DAYS, seed: int = SEED,
                         ci_level: float = CI_LEVEL) -> tuple[float, float, float, float]:
    """Média, IC e p-valor unilateral (H0: média <= 0) reamostrando blocos de `block_days` do calendário."""
    if values.size == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    ids = entry_days // block_days
    _, inverse = np.unique(ids, return_inverse=True)
    k = int(inverse.max()) + 1
    sums = np.bincount(inverse, weights=values, minlength=k).astype("float64")
    counts = np.bincount(inverse, minlength=k).astype("float64")
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, k, size=(resamples, k))
    draws = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    alpha = 1.0 - ci_level
    low, high = np.quantile(draws, [alpha / 2.0, 1.0 - alpha / 2.0])
    p_value = (1.0 + float(np.sum(draws <= 0.0))) / (resamples + 1.0)
    return float(values.mean()), float(low), float(high), float(p_value)


def _summarize(group: pd.DataFrame, column: str, *, resamples: int, seed: int) -> dict[str, float]:
    excess = (group[column] - group["ret_random"]).to_numpy(dtype="float64")
    days = np.asarray(((group["entry_date"] - pd.Timestamp("2000-01-01", tz="UTC")).dt.days).to_numpy(), dtype=np.int64)
    mean_excess, low, high, p_value = block_bootstrap_mean(excess, days, resamples=resamples, seed=seed)
    return {
        "n_trades": float(len(group)), "mean_return": float(group[column].mean()),
        "mean_random": float(group["ret_random"].mean()), "mean_excess": mean_excess,
        "ci_low": low, "ci_high": high, "p_value": p_value,
    }


def evaluate(trades: pd.DataFrame, *, resamples: int = RESAMPLES, seed: int = SEED,
             min_trades: int = MIN_TRADES) -> pd.DataFrame:
    """Tabela de resultados (RESULT_COLUMNS) por configuração, tipo de entrada e período, com Holm e veredito."""
    rows: list[dict[str, object]] = []
    pairs = sorted(set(zip(trades["lookback"].astype(int).tolist(), trades["hold"].astype(int).tolist(), strict=True)))
    for lookback, hold in pairs:
        cfg = trades[(trades["lookback"] == lookback) & (trades["hold"] == hold)]
        for entry, column in ((ENTRY_HONEST, "ret_honest"), (ENTRY_BIASED, "ret_biased")):
            for period in (PERIOD_DEV, PERIOD_TEST):
                sub = cfg[cfg["period"].eq(period)]
                if sub.empty:
                    continue
                stats = _summarize(sub, column, resamples=resamples, seed=seed)
                rows.append({"lookback": lookback, "hold": hold, "entry": entry, "period": period,
                             "p_holm": float("nan"), "status": "", **stats})
    deciding = [r for r in rows if r["entry"] == ENTRY_HONEST and r["period"] == PERIOD_DEV]
    if deciding:
        names = {f"{r['lookback']}/{r['hold']}": float(str(r["p_value"])) for r in deciding}
        adjusted = holm(names)
        holm_by_name = dict(zip(adjusted["hypothesis"].tolist(), adjusted["p_holm"].tolist(), strict=True))
        test_excess = {(r["lookback"], r["hold"]): float(str(r["mean_excess"])) for r in rows
                       if r["entry"] == ENTRY_HONEST and r["period"] == PERIOD_TEST}
        for r in deciding:
            r["p_holm"] = float(holm_by_name[f"{r['lookback']}/{r['hold']}"])
            r["status"] = _verdict(r, test_excess.get((r["lookback"], r["hold"])), min_trades)
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def _verdict(row: dict[str, object], test_excess: float | None, min_trades: int) -> str:
    """Veredito da entrada honesta no desenvolvimento (a única que decide)."""
    if float(str(row["n_trades"])) < min_trades:
        return STATUS_FEW
    works = (float(str(row["mean_excess"])) > 0.0 and float(str(row["ci_low"])) > 0.0
             and float(str(row["p_holm"])) < 0.05 and test_excess is not None and test_excess > 0.0)
    return STATUS_WORKS if works else STATUS_NOT_SHOWN


def bias_summary(trades: pd.DataFrame, hold: int, lookback: int) -> pd.DataFrame:
    """Três barras para a figura: média líquida com viés, honesta e comprando no acaso (todas as operações da config)."""
    sub = trades[(trades["hold"] == hold) & (trades["lookback"] == lookback)]
    return pd.DataFrame({
        "label": ["Com viés (compra no fundo)", "Honesta (compra após confirmar)", "Acaso (qualquer dia)"],
        "mean_return": [float(sub["ret_biased"].mean()), float(sub["ret_honest"].mean()), float(sub["ret_random"].mean())],
        "n_trades": [len(sub)] * 3,
    })
