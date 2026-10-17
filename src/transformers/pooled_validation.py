"""Teste agregado da regra SMA 200 com todas as moedas juntas. Protocolo: docs/pooled_validation.md (fixado antes).

Puro (CLAUDE.md §1). Reaproveita de `signal_validation` os sinais, os retornos futuros líquidos e a referência por moeda;
a inferência é por bootstrap de janelas de calendário (os sinais de moedas diferentes no mesmo mês não são independentes).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .signal_validation import (
    Prepared,
    ValidationRules,
    _window,
    independent_positions,
    stable_seed,
)
from .stats import holm_adjust

CLUSTER_DAYS = 30
HOLDOUT_MIN_POOLED = 20
STATUS_DEMONSTRATED = "DEMONSTRADO"
STATUS_NOT_DEMONSTRATED = "NAO_DEMONSTRADO"
STATUS_REVOKED = "REVOGADO"

SIGNAL_COLUMNS = ("symbol", "day", "ret", "baseline", "excess")
_NAN = float("nan")


def pooled_signals(prep: Prepared, h: int, period: str, rules: ValidationRules) -> pd.DataFrame:
    """Um registro por sinal independente de cada moeda: retorno, média de referência da mesma moeda e excesso."""
    rows: list[dict[str, object]] = []
    forward = prep.forward[h]
    index = forward.index
    for symbol in prep.events.columns:
        fwd = forward[symbol]
        ok = fwd.notna().to_numpy() & _window(index, period, h, rules).to_numpy()
        pos = np.flatnonzero(prep.events[symbol].to_numpy() & ok)
        keep = independent_positions(pos, h)
        base_mask = prep.eligible[symbol].to_numpy() & ok
        if len(keep) == 0 or not base_mask.any():
            continue
        values = fwd.to_numpy(dtype="float64")
        baseline = float(values[base_mask].mean())
        for p in keep.tolist():
            rows.append({"symbol": symbol, "day": index[p], "ret": float(values[p]), "baseline": baseline,
                         "excess": float(values[p]) - baseline})
    out = pd.DataFrame(rows, columns=list(SIGNAL_COLUMNS))
    return out.astype({"symbol": "string", "ret": "float64", "baseline": "float64", "excess": "float64"})


def _cluster_ids(days: pd.Series) -> np.ndarray:
    start = days.min()
    ids: np.ndarray = ((days - start).dt.days // CLUSTER_DAYS).to_numpy(dtype="int64")
    return ids


@dataclass(frozen=True)
class PooledStats:
    n_signals: int
    n_coins: int
    n_clusters: int
    excess: float
    ci_low: float
    ci_high: float
    p_value: float
    stable_halves: bool
    coin_weighted_excess: float
    median_excess: float
    share_coins_positive: float


def pooled_stats(signals: pd.DataFrame, seed: int, resamples: int) -> PooledStats:
    """Excesso médio dos sinais, IC 95% e valor-p unilateral por bootstrap de janelas de calendário de 30 dias."""
    n = len(signals)
    if n == 0:
        return PooledStats(0, 0, 0, _NAN, _NAN, _NAN, _NAN, False, _NAN, _NAN, _NAN)
    ordered = signals.sort_values("day", kind="stable")
    excess = ordered["excess"].to_numpy(dtype="float64")
    ids = _cluster_ids(ordered["day"])
    _, compact = np.unique(ids, return_inverse=True)
    k = int(compact.max()) + 1
    sums = np.bincount(compact, weights=excess, minlength=k)
    counts = np.bincount(compact, minlength=k).astype("float64")
    observed = float(excess.mean())
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, k, size=(resamples, k))
    boot = sums[draw].sum(axis=1) / np.maximum(counts[draw].sum(axis=1), 1.0)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    p = (1.0 + float(np.sum(boot - observed >= observed))) / (resamples + 1.0)
    half = n // 2
    stable = bool(n >= 2 and excess[:half].mean() > 0 and excess[half:].mean() > 0)
    per_coin = ordered.groupby("symbol", observed=True)["excess"].mean()
    return PooledStats(
        n, int(per_coin.shape[0]), k, observed, float(lo), float(hi), p, stable,
        float(per_coin.mean()), float(np.median(excess)), float((per_coin > 0).mean()),
    )


def evaluate_pooled(prep: Prepared, rules: ValidationRules = ValidationRules()) -> pd.DataFrame:
    """Desenvolvimento: uma linha por horizonte, com Holm sobre os horizontes e o veredito geral na coluna `status`."""
    rows = []
    for h in rules.horizons:
        s = pooled_stats(pooled_signals(prep, h, "DESENVOLVIMENTO", rules), stable_seed(rules.seed, "POOLED", h), rules.resamples)
        rows.append({"horizon": h, "n_signals": s.n_signals, "n_coins": s.n_coins, "n_clusters": s.n_clusters,
                     "excess": s.excess, "ci_low": s.ci_low, "ci_high": s.ci_high, "p_value": s.p_value,
                     "stable_halves": s.stable_halves, "coin_weighted_excess": s.coin_weighted_excess,
                     "median_excess": s.median_excess, "share_coins_positive": s.share_coins_positive})
    frame = pd.DataFrame(rows)
    frame["p_holm"] = holm_adjust(frame["p_value"].tolist())
    passed = frame["p_holm"].lt(rules.alpha) & frame["ci_low"].gt(0) & frame["stable_halves"]
    frame["passed"] = passed
    frame["status"] = STATUS_DEMONSTRATED if bool(passed.all()) else STATUS_NOT_DEMONSTRATED
    return frame


def apply_pooled_holdout(dev: pd.DataFrame, prep: Prepared, rules: ValidationRules = ValidationRules()) -> pd.DataFrame:
    """Só avalia o teste final se o desenvolvimento passou; só pode revogar (>= 20 sinais e excesso médio negativo)."""
    out = dev.assign(holdout_n=pd.array([pd.NA] * len(dev), dtype="Int64"), holdout_excess=_NAN)
    if not bool(dev["status"].eq(STATUS_DEMONSTRATED).all()):
        return out
    for i, h in enumerate(dev["horizon"].tolist()):
        sig = pooled_signals(prep, int(h), "TESTE_FINAL", rules)
        out.loc[out.index[i], "holdout_n"] = len(sig)
        out.loc[out.index[i], "holdout_excess"] = float(sig["excess"].mean()) if len(sig) else _NAN
    revoked = out["holdout_n"].fillna(0).ge(HOLDOUT_MIN_POOLED) & out["holdout_excess"].lt(0)
    if bool(revoked.any()):
        out["status"] = STATUS_REVOKED
    return out


def sensitivity(signals: pd.DataFrame, exclude: set[str], seed: int, resamples: int) -> PooledStats:
    """O mesmo teste sem as moedas de `exclude` (apenas descritivo)."""
    return pooled_stats(signals[~signals["symbol"].astype(str).isin(exclude)], seed, resamples)


def top_by_signals(signals: pd.DataFrame, k: int) -> set[str]:
    return set(signals["symbol"].astype(str).value_counts().head(k).index)


