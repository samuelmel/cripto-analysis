"""Estatística dos sinais de entrada candidatos: excesso, Holm, níveis e teste final. Protocolo: docs/entry_signals.md.

Puro (CLAUDE.md §1). A inferência é a do teste agregado (`pooled_validation.pooled_stats`: bootstrap por janelas de
calendário de 30 dias); muda só a referência, conforme o tipo do sinal:
    SELECAO (A, D, E, F)  média do universo point-in-time no mesmo dia, peso igual, mesma execução e custos
    TEMPO   (B, C)        média de entrar em qualquer dia elegível da mesma moeda (mesmo período)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .entry_signals import KIND_CROSS, KIND_TIMING
from .pooled_validation import CLUSTER_DAYS, SIGNAL_COLUMNS, pooled_stats
from .signal_validation import ValidationRules, _window, independent_positions, stable_seed
from .stats import holm_adjust

LEVEL_VALIDATED = "VALIDADO"
LEVEL_PROMISING = "PROMISSOR"
LEVEL_NO_EVIDENCE = "SEM_EVIDENCIA"
LEVELS: tuple[str, ...] = (LEVEL_VALIDATED, LEVEL_PROMISING, LEVEL_NO_EVIDENCE)

HOLDOUT_CONTRADICTED = "CONTRADITO"
HOLDOUT_NOT_CONTRADICTED = "NAO_CONTRADITO"
HOLDOUT_INSUFFICIENT = "INSUFICIENTE"   # menos de 20 sinais em algum horizonte: "não confirmado no teste final"
HOLDOUT_NOT_ASSESSED = "NAO_AVALIADO"   # SEM_EVIDENCIA no desenvolvimento: teste final não se aplica
HOLDOUT_MIN_SIGNALS = 20

DEV = "DESENVOLVIMENTO"
FINAL = "TESTE_FINAL"

STATS_SCHEMA: dict[str, str] = {
    "combo": "string",
    "candidate": "string",
    "kind": "string",
    "execution": "string",
    "horizon": "int64",
    "n_signals": "int64",
    "n_coins": "int64",
    "n_clusters": "int64",
    "excess": "float64",
    "ci_low": "float64",
    "ci_high": "float64",
    "p_value": "float64",
    "p_holm": "float64",
    "stable_halves": "bool",
    "coin_weighted_excess": "float64",
    "median_excess": "float64",
    "share_coins_positive": "float64",
    "holdout_n": "Int64",
    "holdout_excess": "float64",
}

LEVEL_SCHEMA: dict[str, str] = {
    "combo": "string",
    "candidate": "string",
    "kind": "string",
    "level": "string",
    "dev_level": "string",
    "holdout": "string",
    "excess_7": "float64",
    "ci_low_7": "float64",
    "ci_high_7": "float64",
    "p_holm_7": "float64",
    "n_signals_7": "int64",
    "excess_30": "float64",
    "ci_low_30": "float64",
    "ci_high_30": "float64",
    "p_holm_30": "float64",
    "n_signals_30": "int64",
    "holdout_n_7": "Int64",
    "holdout_n_30": "Int64",
    "holdout_excess_7": "float64",
    "holdout_excess_30": "float64",
    "reason": "string",
}

_NAN = float("nan")


def signal_table(
    events: pd.DataFrame,
    calculable: pd.DataFrame,
    forward: pd.DataFrame,
    reference: pd.Series,
    kind: str,
    h: int,
    period: str,
    rules: ValidationRules,
) -> pd.DataFrame:
    """Um registro por sinal independente: retorno líquido, referência e excesso. `reference` é a média do universo por
    dia (usada só em SELECAO)."""
    if kind not in (KIND_CROSS, KIND_TIMING):
        raise ValueError(f"tipo de sinal desconhecido: {kind!r}")
    index = forward.index
    window = _window(index, period, h, rules).to_numpy()
    ref = reference.reindex(index).to_numpy(dtype="float64")
    rows: list[dict[str, object]] = []
    for symbol in events.columns:
        values = forward[symbol].to_numpy(dtype="float64")
        ok = ~np.isnan(values) & window
        keep = independent_positions(np.flatnonzero(events[symbol].to_numpy(dtype=bool) & ok), h)
        if len(keep) == 0:
            continue
        if kind == KIND_TIMING:
            base_mask = calculable[symbol].to_numpy(dtype=bool) & ok
            if not base_mask.any():
                continue
            baselines = np.full(len(keep), float(values[base_mask].mean()))
        else:
            baselines = ref[keep]
        for p, b in zip(keep.tolist(), baselines.tolist(), strict=True):
            if np.isnan(b):
                continue
            rows.append({"symbol": symbol, "day": index[p], "ret": float(values[p]), "baseline": float(b),
                         "excess": float(values[p]) - float(b)})
    out = pd.DataFrame(rows, columns=list(SIGNAL_COLUMNS))
    return out.astype({"symbol": "string", "ret": "float64", "baseline": "float64", "excess": "float64"})


@dataclass(frozen=True)
class ComboSpec:
    combo_id: str
    candidate: str
    kind: str


def stats_rows(
    tables: Mapping[tuple[str, int], pd.DataFrame],
    specs: Mapping[str, ComboSpec],
    execution: str,
    rules: ValidationRules,
) -> pd.DataFrame:
    """Estatística de cada (combinação, horizonte); `p_holm` fica NaN (o Holm é aplicado sobre a família inteira)."""
    rows = []
    for (combo, h), table in tables.items():
        spec = specs[combo]
        s = pooled_stats(table, stable_seed(rules.seed, "ENTRY", combo, h, execution), rules.resamples)
        rows.append({"combo": combo, "candidate": spec.candidate, "kind": spec.kind, "execution": execution,
                     "horizon": h, "n_signals": s.n_signals, "n_coins": s.n_coins, "n_clusters": s.n_clusters,
                     "excess": s.excess, "ci_low": s.ci_low, "ci_high": s.ci_high, "p_value": s.p_value,
                     "p_holm": _NAN, "stable_halves": s.stable_halves,
                     "coin_weighted_excess": s.coin_weighted_excess, "median_excess": s.median_excess,
                     "share_coins_positive": s.share_coins_positive, "holdout_n": pd.NA, "holdout_excess": _NAN})
    return pd.DataFrame(rows, columns=list(STATS_SCHEMA)).astype(STATS_SCHEMA)


def apply_holm(frame: pd.DataFrame) -> pd.DataFrame:
    """Holm sobre todas as linhas (a família inteira); hipótese sem valor-p (sem sinais) conta com p = 1."""
    p = frame["p_value"].fillna(1.0).tolist()
    return frame.assign(p_holm=holm_adjust(p) if p else [])


def _passes(row: pd.Series, alpha: float) -> bool:
    return bool(row["p_holm"] < alpha and row["ci_low"] > 0 and row["stable_halves"])


def dev_level(per_h: Mapping[int, pd.Series], alpha: float) -> tuple[str, str]:
    """Nível no desenvolvimento e o motivo. VALIDADO: os dois horizontes passam; PROMISSOR: excesso > 0 nos dois."""
    if all(_passes(r, alpha) for r in per_h.values()):
        return LEVEL_VALIDATED, "passou nos dois horizontes (Holm, IC e metades)"
    if all(float(r["excess"]) > 0 for r in per_h.values()):
        return LEVEL_PROMISING, "excesso médio > 0 nos dois horizontes, sem significância"
    negative = [str(h) for h, r in per_h.items() if not float(r["excess"]) > 0]
    return LEVEL_NO_EVIDENCE, f"excesso médio <= 0 ou indisponível em {'/'.join(negative)} dias"


def holdout_verdict(per_h: Mapping[int, tuple[int, float]], minimum: int = HOLDOUT_MIN_SIGNALS) -> str:
    """Contradição = pelo menos `minimum` sinais e excesso médio negativo em algum horizonte."""
    if any(n >= minimum and ex < 0 for n, ex in per_h.values()):
        return HOLDOUT_CONTRADICTED
    if all(n >= minimum for n, _ in per_h.values()):
        return HOLDOUT_NOT_CONTRADICTED
    return HOLDOUT_INSUFFICIENT


def final_level(dev: str, holdout: str) -> str:
    """O teste final só rebaixa: VALIDADO ou PROMISSOR contradito vira SEM_EVIDENCIA."""
    if dev in (LEVEL_VALIDATED, LEVEL_PROMISING) and holdout == HOLDOUT_CONTRADICTED:
        return LEVEL_NO_EVIDENCE
    return dev


def levels(
    stats: pd.DataFrame,
    holdout: Mapping[tuple[str, int], tuple[int, float]],
    horizons: tuple[int, ...],
    alpha: float,
) -> pd.DataFrame:
    """Nível final de cada combinação. `holdout`: (combo, h) -> (sinais, excesso médio) no teste final, só para as
    combinações VALIDADO/PROMISSOR no desenvolvimento (as outras não gastam o teste final)."""
    rows = []
    for combo, group in stats.groupby("combo", sort=False):
        per_h = {int(r["horizon"]): r for _, r in group.iterrows()}
        dev, why = dev_level({h: per_h[h] for h in horizons}, alpha)
        hold = {h: holdout[(str(combo), h)] for h in horizons if (str(combo), h) in holdout}
        verdict = holdout_verdict(hold) if dev != LEVEL_NO_EVIDENCE and len(hold) == len(horizons) else HOLDOUT_NOT_ASSESSED
        level = final_level(dev, verdict)
        if level != dev:
            why = f"{why}; contradito no teste final"
        elif dev == LEVEL_VALIDATED and verdict == HOLDOUT_INSUFFICIENT:
            why = f"{why}; não confirmado no teste final (menos de {HOLDOUT_MIN_SIGNALS} sinais)"
        first = group.iloc[0]
        row: dict[str, object] = {"combo": combo, "candidate": first["candidate"], "kind": first["kind"],
                                  "level": level, "dev_level": dev, "holdout": verdict, "reason": why}
        for h in (7, 30):
            r = per_h.get(h)
            row[f"excess_{h}"] = float(r["excess"]) if r is not None else _NAN
            row[f"ci_low_{h}"] = float(r["ci_low"]) if r is not None else _NAN
            row[f"ci_high_{h}"] = float(r["ci_high"]) if r is not None else _NAN
            row[f"p_holm_{h}"] = float(r["p_holm"]) if r is not None else _NAN
            row[f"n_signals_{h}"] = int(r["n_signals"]) if r is not None else 0
            n_ex = hold.get(h)
            row[f"holdout_n_{h}"] = n_ex[0] if n_ex is not None else pd.NA
            row[f"holdout_excess_{h}"] = n_ex[1] if n_ex is not None else _NAN
        rows.append(row)
    return pd.DataFrame(rows, columns=list(LEVEL_SCHEMA)).astype(LEVEL_SCHEMA)


@dataclass(frozen=True)
class PairedDifference:
    n_f: int
    n_a: int
    n_clusters: int
    difference: float
    ci_low: float
    ci_high: float


def paired_difference(
    signals_f: pd.DataFrame, signals_a: pd.DataFrame, origin: pd.Timestamp, seed: int, resamples: int
) -> PairedDifference:
    """Excesso médio de F menos o de A, com o mesmo sorteio de janelas de calendário de 30 dias para os dois (pareado)."""
    if signals_f.empty or signals_a.empty:
        return PairedDifference(len(signals_f), len(signals_a), 0, _NAN, _NAN, _NAN)

    def ids(frame: pd.DataFrame) -> np.ndarray:
        out: np.ndarray = ((frame["day"] - origin).dt.days // CLUSTER_DAYS).to_numpy(dtype="int64")
        return out

    id_f, id_a = ids(signals_f), ids(signals_a)
    clusters = np.unique(np.concatenate([id_f, id_a]))
    k = len(clusters)
    pos_f, pos_a = np.searchsorted(clusters, id_f), np.searchsorted(clusters, id_a)
    ex_f = signals_f["excess"].to_numpy(dtype="float64")
    ex_a = signals_a["excess"].to_numpy(dtype="float64")
    sum_f = np.bincount(pos_f, weights=ex_f, minlength=k)
    cnt_f = np.bincount(pos_f, minlength=k).astype("float64")
    sum_a = np.bincount(pos_a, weights=ex_a, minlength=k)
    cnt_a = np.bincount(pos_a, minlength=k).astype("float64")
    observed = float(ex_f.mean() - ex_a.mean())
    draw = np.random.default_rng(seed).integers(0, k, size=(resamples, k))
    mean_f = sum_f[draw].sum(axis=1) / np.maximum(cnt_f[draw].sum(axis=1), 1.0)
    mean_a = sum_a[draw].sum(axis=1) / np.maximum(cnt_a[draw].sum(axis=1), 1.0)
    lo, hi = np.percentile(mean_f - mean_a, [2.5, 97.5])
    return PairedDifference(len(signals_f), len(signals_a), k, observed, float(lo), float(hi))
