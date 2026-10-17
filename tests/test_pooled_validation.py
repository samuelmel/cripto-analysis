"""Teste agregado (todas as moedas juntas): detecta efeito, rejeita ruído, trata dependência e usa o hold-out só para revogar."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.transformers.pooled_validation import (
    STATUS_DEMONSTRATED,
    STATUS_NOT_DEMONSTRATED,
    STATUS_REVOKED,
    apply_pooled_holdout,
    evaluate_pooled,
    pooled_signals,
    pooled_stats,
    sensitivity,
)
from src.transformers.signal_validation import ValidationRules
from tests.test_signal_validation import synthetic

RULES = ValidationRules(n_min=12, null_draws=2000, resamples=800)


def spec(dev: float, hold: float, n_hold: int = 12, coins: int = 25) -> dict[str, tuple[float, int, float, int]]:
    return {f"C{i}/USDT": (dev, 8, hold, n_hold) for i in range(coins)}


def test_injected_effect_is_demonstrated_in_both_horizons() -> None:
    dev = evaluate_pooled(synthetic(spec(0.05, 0.05)), RULES)
    assert set(dev["status"]) == {STATUS_DEMONSTRATED}
    assert (dev["ci_low"] > 0).all() and (dev["p_holm"] < 0.05).all()


def test_noise_is_not_demonstrated() -> None:
    dev = evaluate_pooled(synthetic(spec(0.0, 0.0)), RULES)
    assert set(dev["status"]) == {STATUS_NOT_DEMONSTRATED}


def test_holdout_is_not_computed_when_development_fails() -> None:
    prep = synthetic(spec(0.0, 0.30))
    final = apply_pooled_holdout(evaluate_pooled(prep, RULES), prep, RULES)
    assert set(final["status"]) == {STATUS_NOT_DEMONSTRATED}
    assert final["holdout_n"].isna().all()  # o teste final não foi gasto


def test_holdout_can_only_revoke() -> None:
    kept = synthetic(spec(0.05, 0.05))
    assert set(apply_pooled_holdout(evaluate_pooled(kept, RULES), kept, RULES)["status"]) == {STATUS_DEMONSTRATED}
    flop = synthetic(spec(0.05, -0.20))
    assert set(apply_pooled_holdout(evaluate_pooled(flop, RULES), flop, RULES)["status"]) == {STATUS_REVOKED}
    thin = synthetic(spec(0.05, -0.20, n_hold=0))
    out = apply_pooled_holdout(evaluate_pooled(thin, RULES), thin, RULES)
    assert set(out["status"]) == {STATUS_DEMONSTRATED}  # sem sinais suficientes no teste final: nem refuta


def test_development_verdict_ignores_the_holdout() -> None:
    a = evaluate_pooled(synthetic(spec(0.0, 0.0)), RULES)
    b = evaluate_pooled(synthetic(spec(0.0, 5.0)), RULES)
    pd.testing.assert_frame_equal(a, b)


def test_same_seed_same_result_other_seed_different_interval() -> None:
    sig = pooled_signals(synthetic(spec(0.02, 0.0)), 30, "DESENVOLVIMENTO", RULES)
    a, b, c = pooled_stats(sig, 7, 800), pooled_stats(sig, 7, 800), pooled_stats(sig, 8, 800)
    assert a == b and a.ci_low != c.ci_low


def test_cluster_bootstrap_is_wider_than_treating_signals_as_independent() -> None:
    """25 moedas com o mesmo choque no mesmo dia: o erro verdadeiro é o de ~8 observações, não o de 200."""
    idx = pd.date_range("2020-01-01", periods=8 * 31, freq="D", tz="UTC")
    rng = np.random.default_rng(3)
    shocks = rng.normal(0.0, 0.10, 8)
    rows = [{"symbol": f"C{c}/USDT", "day": idx[j * 31], "ret": 0.0, "baseline": 0.0,
             "excess": float(shocks[j] + rng.normal(0.0, 0.01))} for c in range(25) for j in range(8)]
    sig = pd.DataFrame(rows).astype({"symbol": "string"})
    s = pooled_stats(sig, 5, 2000)
    naive = 1.96 * sig["excess"].std() / np.sqrt(len(sig))
    assert (s.ci_high - s.ci_low) / 2 > 3 * naive
    assert s.n_clusters == 8


def test_only_independent_signals_per_coin_and_excess_uses_the_same_coin() -> None:
    prep = synthetic({"A/USDT": (0.05, 8, 0.0, 0)})
    sig = pooled_signals(prep, 30, "DESENVOLVIMENTO", RULES)
    days = pd.to_datetime(sig["day"]).sort_values()
    assert (days.diff().dropna().dt.days >= 30).all()
    assert np.allclose(sig["excess"], sig["ret"] - sig["baseline"])
    assert sig["baseline"].nunique() == 1


def test_sensitivity_excludes_coins() -> None:
    sig = pooled_signals(synthetic(spec(0.05, 0.0, n_hold=0, coins=5)), 7, "DESENVOLVIMENTO", RULES)
    s = sensitivity(sig, {"C0/USDT", "C1/USDT"}, 1, 300)
    assert s.n_coins == 3
