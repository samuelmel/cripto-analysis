"""Estudo da IA: os modelos em sombra contra o universo e contra o momento simples. Protocolo: docs/ml_study.md.

Puro (CLAUDE.md §1): recebe as linhas de features/alvo, o painel de preços e as configurações; devolve tabelas.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .bootstrap import BootstrapConfig, bootstrap_statistic, make_resampler, optimal_block_length
from .entry_signals import EXECUTION_OPEN, Panel, forward_returns, top_k, trailing_return, universe_reference
from .model_shadow import FNG_FEATURES, MODELS, ModelSpec, usable, walk_forward
from .multiple_testing import holm

LEVEL_VALIDATED = "VALIDADO"
LEVEL_PROMISING = "PROMISSOR"
LEVEL_NONE = "SEM_EVIDENCIA"
LEVEL_NOT_RUN = "NAO_EXECUTADO"
HYP_UNIVERSE = "universo"
HYP_MOMENTUM = "momento"


@dataclass(frozen=True)
class StudyRules:
    years: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024, 2025, 2026)
    development_end: pd.Timestamp = pd.Timestamp("2024-12-31", tz="UTC")
    holdout_start: pd.Timestamp = pd.Timestamp("2025-01-01", tz="UTC")
    horizon: int = 30
    top_k: int = 5
    min_universe: int = 10
    momentum_days: int = 90
    alpha: float = 0.05
    min_block: float = 30.0
    boot: BootstrapConfig = BootstrapConfig(n_boot=2000, seed=20261019, ci_level=0.95)
    sensitivity_k: tuple[int, ...] = (3, 10)


# ---------------------------------------------------------------------------------------------
# Métricas preditivas
# ---------------------------------------------------------------------------------------------

def auc(prob: np.ndarray, target: np.ndarray) -> float:
    """Área sob a curva ROC pelo posto médio (empates contam meio)."""
    pos = target == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return math.nan
    ranks = pd.Series(prob).rank(method="average").to_numpy()
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def log_loss(prob: np.ndarray, target: np.ndarray) -> float:
    p = np.clip(prob, 1e-12, 1 - 1e-12)
    return float(-np.mean(target * np.log(p) + (1 - target) * np.log(1 - p)))


def predictive_row(model: str, period: str, prob: np.ndarray, target: np.ndarray, base_rate: float) -> dict[str, object]:
    """AUC, log loss, Brier e ganho de log loss sobre prever a taxa de positivos do treino."""
    if len(prob) == 0:
        nan = math.nan
        return {"model": model, "period": period, "n": 0, "auc": nan, "log_loss": nan, "brier": nan,
                "log_loss_base": nan, "skill": nan, "positive_rate": nan}
    ll = log_loss(prob, target)
    ll_base = log_loss(np.full(len(target), base_rate), target)
    return {"model": model, "period": period, "n": len(prob), "auc": auc(prob, target), "log_loss": ll,
            "brier": float(np.mean((prob - target) ** 2)), "log_loss_base": ll_base, "skill": 1.0 - ll / ll_base,
            "positive_rate": float(target.mean())}


def calibration(model: str, period: str, prob: np.ndarray, target: np.ndarray) -> pd.DataFrame:
    """Probabilidade média prevista e frequência observada por decil de probabilidade."""
    if len(prob) < 10:
        return pd.DataFrame(columns=["model", "period", "decile", "n", "mean_prob", "observed"])
    decile = pd.qcut(pd.Series(prob).rank(method="first"), 10, labels=False)
    frame = pd.DataFrame({"decile": decile, "prob": prob, "target": target})
    out = frame.groupby("decile").agg(n=("prob", "size"), mean_prob=("prob", "mean"), observed=("target", "mean")).reset_index()
    return out.assign(model=model, period=period)[["model", "period", "decile", "n", "mean_prob", "observed"]]


# ---------------------------------------------------------------------------------------------
# Métrica econômica
# ---------------------------------------------------------------------------------------------

def daily_excess(scores: pd.DataFrame, forward: pd.DataFrame, member: pd.DataFrame, k: int, min_universe: int) -> pd.Series:
    """Excesso diário: retorno futuro médio das `k` de maior escore − média do universo do dia. Só dias com pelo menos
    `min_universe` moedas com escore e retorno futuro."""
    ok = member & scores.notna() & forward.notna()
    chosen = top_k(scores, ok, k)
    n = ok.sum(axis=1)
    top = forward.where(chosen).mean(axis=1, skipna=True)
    ref = universe_reference(forward, ok)
    out: pd.Series = (top - ref).where(n >= min_universe)
    return out.dropna()


def mean_test(series: pd.Series, rules: StudyRules) -> dict[str, float]:
    """Média, IC e p unilateral (H0: média <= 0) por bootstrap estacionário com bloco >= `min_block`."""
    x = series.to_numpy("float64")
    if len(x) < 2 * rules.min_block:
        nan = math.nan
        return {"n_days": float(len(x)), "mean": float(x.mean()) if len(x) else nan, "ci_low": nan, "ci_high": nan, "p_value": nan, "block": nan}
    block = max(optimal_block_length(x), optimal_block_length(np.abs(x - x.mean())), rules.min_block)
    cfg = BootstrapConfig(n_boot=rules.boot.n_boot, seed=rules.boot.seed, ci_level=rules.boot.ci_level, block=block)
    e = bootstrap_statistic(x, lambda m: m.mean(axis=1), make_resampler([x], cfg))
    return {"n_days": float(len(x)), "mean": e.estimate, "ci_low": e.ci_low, "ci_high": e.ci_high, "p_value": e.p_value,
            "block": e.block}


def paired_test(a: pd.Series, b: pd.Series, rules: StudyRules) -> dict[str, float]:
    """Diferença das médias de `a` e `b` nos dias em comum, reamostrando os mesmos dias."""
    both = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    return mean_test(both["a"] - both["b"], rules)


def classify_model(dev_universe: Mapping[str, float], dev_momentum: Mapping[str, float], p_holm_u: float, p_holm_m: float,
                   test_universe: float, test_momentum: float, alpha: float) -> tuple[str, str]:
    """Nível e motivo, pelas regras de docs/ml_study.md."""
    u, m = float(dev_universe["mean"]), float(dev_momentum["mean"])
    not_contradicted = test_universe > 0 and test_momentum > 0
    significant = (p_holm_u < alpha and p_holm_m < alpha and float(dev_universe["ci_low"]) > 0
                   and float(dev_momentum["ci_low"]) > 0)
    if significant and not_contradicted:
        return LEVEL_VALIDATED, "as duas hipóteses sobrevivem ao Holm e o teste final não contradiz"
    if u > 0 and m > 0 and not_contradicted:
        why = "excessos positivos no desenvolvimento e no teste final, mas sem significância após Holm"
        return LEVEL_PROMISING, why if not significant else "significativo no desenvolvimento, mas contradito no teste final"
    parts = []
    if not u > 0:
        parts.append("não supera o universo no desenvolvimento")
    if not m > 0:
        parts.append("não supera o momento simples no desenvolvimento")
    if not not_contradicted:
        parts.append("contradito no teste final")
    return LEVEL_NONE, "; ".join(parts) or "sem evidência"


@dataclass(frozen=True)
class _Outcome:
    universe: dict[str, float]
    momentum: dict[str, float]
    hold_universe: float
    hold_momentum: float


@dataclass(frozen=True)
class StudyResult:
    predictive: pd.DataFrame
    calibration: pd.DataFrame
    tests: pd.DataFrame
    levels: pd.DataFrame
    sensitivity: pd.DataFrame
    folds: pd.DataFrame
    daily: pd.DataFrame


def run_study(rows: pd.DataFrame, panel: Panel, fng_available: bool, rules: StudyRules = StudyRules(),
              specs: Sequence[ModelSpec] = MODELS) -> StudyResult:
    """O estudo inteiro (ver docs/ml_study.md)."""
    index, columns = pd.DatetimeIndex(panel.close.index), panel.close.columns
    forward = forward_returns(panel, rules.horizon, EXECUTION_OPEN)
    forward_close = forward_returns(panel, rules.horizon, "FECHAMENTO")
    momentum = trailing_return(panel.close, rules.momentum_days)
    first_day = pd.Timestamp(f"{rules.years[0]}-01-01", tz="UTC")

    def split(s: pd.Series) -> tuple[pd.Series, pd.Series]:
        days = pd.DatetimeIndex(s.index)
        return s[(days >= first_day) & (days <= rules.development_end)], s[days >= rules.holdout_start]

    mom_series = daily_excess(momentum, forward, panel.member, rules.top_k, rules.min_universe)
    mom_dev, mom_hold = split(mom_series)
    predictive, calib, tests, sens, folds_all, daily = [], [], [], [], [], {"MOMENTO_90D": mom_series}
    pvals: dict[str, float] = {}
    per_model: dict[str, _Outcome | None] = {}
    for spec in specs:
        needs_fng = any(f in FNG_FEATURES for f in spec.features)
        if needs_fng and not fng_available:
            per_model[spec.name] = None
            pvals[f"{spec.name}|{HYP_UNIVERSE}"] = math.nan
            pvals[f"{spec.name}|{HYP_MOMENTUM}"] = math.nan
            continue
        prob, folds = walk_forward(spec, rows, rules.years)
        folds_all.append(folds)
        data = usable(rows, spec).reindex(prob.index)
        target = data["target"]
        known = target.notna().to_numpy()
        pdays = pd.DatetimeIndex(prob.index.get_level_values("timestamp"))
        base = float(folds["positive_rate"].mean()) if not folds.empty else 0.5
        for period, mask in (("DESENVOLVIMENTO", pdays <= rules.development_end), ("TESTE_FINAL", pdays >= rules.holdout_start)):
            sel = mask & known
            p, y = prob.to_numpy()[sel], target.to_numpy("float64")[sel]
            predictive.append(predictive_row(spec.name, period, p, y, base))
            calib.append(calibration(spec.name, period, p, y))
        wide = prob.unstack("symbol").reindex(index=index, columns=columns).astype("float64")
        series = daily_excess(wide, forward, panel.member, rules.top_k, rules.min_universe)
        daily[spec.name] = series
        s_dev, s_hold = split(series)
        u = mean_test(s_dev, rules)
        m = paired_test(s_dev, mom_dev, rules)
        hold_u = float(s_hold.mean()) if len(s_hold) else math.nan
        both_hold = pd.concat([s_hold.rename("a"), mom_hold.rename("b")], axis=1).dropna()
        hold_m = float((both_hold["a"] - both_hold["b"]).mean()) if len(both_hold) else math.nan
        pvals[f"{spec.name}|{HYP_UNIVERSE}"] = u["p_value"]
        pvals[f"{spec.name}|{HYP_MOMENTUM}"] = m["p_value"]
        per_model[spec.name] = _Outcome(u, m, hold_u, hold_m)
        for k in rules.sensitivity_k:
            sk = split(daily_excess(wide, forward, panel.member, k, rules.min_universe))[0]
            sens.append({"model": spec.name, "variant": f"k={k}", "mean": float(sk.mean()), "n_days": len(sk)})
        sc = split(daily_excess(wide, forward_close, panel.member, rules.top_k, rules.min_universe))[0]
        sens.append({"model": spec.name, "variant": "execucao_fechamento", "mean": float(sc.mean()), "n_days": len(sc)})

    family_table = holm(pvals, rules.alpha)
    p_holm = dict(zip(family_table["hypothesis"].astype(str), family_table["p_holm"].astype(float), strict=True))
    levels = []
    for spec in specs:
        info = per_model[spec.name]
        if info is None:
            levels.append({"model": spec.name, "level": LEVEL_NOT_RUN, "reason": "Fear & Greed indisponível: não executado (p = 1 na família)"})
            for hyp in (HYP_UNIVERSE, HYP_MOMENTUM):
                tests.append({"model": spec.name, "hypothesis": hyp, "period": "DESENVOLVIMENTO", "n_days": math.nan,
                              "mean": math.nan, "ci_low": math.nan, "ci_high": math.nan, "p_value": math.nan,
                              "p_holm": p_holm[f"{spec.name}|{hyp}"], "block": math.nan,
                              "holdout_mean": math.nan})
            continue
        u, m, hold_u, hold_m = info.universe, info.momentum, info.hold_universe, info.hold_momentum
        pu, pm = p_holm[f"{spec.name}|{HYP_UNIVERSE}"], p_holm[f"{spec.name}|{HYP_MOMENTUM}"]
        for hyp, res, ph, hm in ((HYP_UNIVERSE, u, pu, hold_u), (HYP_MOMENTUM, m, pm, hold_m)):
            tests.append({"model": spec.name, "hypothesis": hyp, "period": "DESENVOLVIMENTO", **res, "p_holm": ph,
                          "holdout_mean": hm})
        level, reason = classify_model(u, m, pu, pm, hold_u, hold_m, rules.alpha)
        levels.append({"model": spec.name, "level": level, "reason": reason})
    ref_dev = mean_test(mom_dev, rules)
    tests.append({"model": "MOMENTO_90D", "hypothesis": "universo (referência, fora da família)", "period": "DESENVOLVIMENTO",
                  **ref_dev, "p_holm": math.nan, "holdout_mean": float(mom_hold.mean()) if len(mom_hold) else math.nan})
    calib_frame = pd.concat([c for c in calib if not c.empty], ignore_index=True) if any(not c.empty for c in calib) else pd.DataFrame()
    return StudyResult(
        predictive=pd.DataFrame(predictive), calibration=calib_frame, tests=pd.DataFrame(tests),
        levels=pd.DataFrame(levels).astype({"model": "string", "level": "string", "reason": "string"}),
        sensitivity=pd.DataFrame(sens), folds=pd.concat(folds_all, ignore_index=True) if folds_all else pd.DataFrame(),
        daily=pd.DataFrame(daily).rename_axis("day").reset_index(),
    )
