"""Estudo da IA: métricas preditivas, excesso do top-k, classificação e o estudo completo em dados sintéticos."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.transformers.bootstrap import BootstrapConfig
from src.transformers.data_quality import clean_candles
from src.transformers.entry_model import model_features, outperform_target
from src.transformers.entry_signals import EntryRules, build_panel
from src.transformers.ml_study import (
    LEVEL_NONE,
    LEVEL_NOT_RUN,
    LEVEL_PROMISING,
    LEVEL_VALIDATED,
    StudyRules,
    auc,
    classify_model,
    daily_excess,
    log_loss,
    mean_test,
    run_study,
)
from src.transformers.model_shadow import stack_all
from tests.synthetic_market import synthetic_candles, synthetic_fng

UTC = "UTC"


def test_auc_and_log_loss_match_known_values() -> None:
    assert auc(np.array([0.1, 0.4, 0.35, 0.8]), np.array([0, 0, 1, 1])) == pytest.approx(0.75)
    assert auc(np.array([0.5, 0.5]), np.array([0, 1])) == pytest.approx(0.5)  # empate conta meio
    assert math.isnan(auc(np.array([0.2]), np.array([1])))
    assert log_loss(np.array([0.5, 0.5]), np.array([0, 1])) == pytest.approx(math.log(2))


def test_daily_excess_is_top_k_minus_universe_and_needs_a_minimum_universe() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="D", tz=UTC)
    cols = [f"C{i}" for i in range(4)]
    scores = pd.DataFrame([[4, 3, 2, 1], [1, 2, 3, 4]], index=idx, columns=cols, dtype="float64")
    fwd = pd.DataFrame([[0.4, 0.2, 0.0, -0.2], [0.4, 0.2, 0.0, -0.2]], index=idx, columns=cols)
    member = pd.DataFrame(True, index=idx, columns=cols)
    out = daily_excess(scores, fwd, member, k=2, min_universe=4)
    assert out.iloc[0] == pytest.approx(0.3 - 0.1) and out.iloc[1] == pytest.approx(-0.1 - 0.1)
    assert daily_excess(scores, fwd, member, k=2, min_universe=5).empty


def test_mean_test_uses_blocks_of_at_least_the_horizon() -> None:
    rng = np.random.default_rng(3)
    s = pd.Series(rng.normal(0.01, 0.05, 600), index=pd.date_range("2021-01-01", periods=600, freq="D", tz=UTC))
    r = mean_test(s, StudyRules(boot=BootstrapConfig(n_boot=300, seed=1, ci_level=0.95)))
    assert r["block"] >= 30 and r["ci_low"] < r["mean"] < r["ci_high"] and 0 <= r["p_value"] <= 1


def test_classification_follows_the_protocol() -> None:
    good = {"mean": 0.02, "ci_low": 0.005}
    weak = {"mean": 0.01, "ci_low": -0.01}
    assert classify_model(good, good, 0.01, 0.02, 0.01, 0.01, 0.05)[0] == LEVEL_VALIDATED
    assert classify_model(good, good, 0.01, 0.02, -0.01, 0.01, 0.05)[0] == LEVEL_NONE      # contradito no teste
    assert classify_model(weak, weak, 0.4, 0.5, 0.01, 0.01, 0.05)[0] == LEVEL_PROMISING
    assert classify_model(good, good, 0.2, 0.02, 0.01, 0.01, 0.05)[0] == LEVEL_PROMISING   # não sobrevive ao Holm
    assert classify_model({"mean": -0.01, "ci_low": -0.03}, good, 0.9, 0.01, 0.01, 0.01, 0.05)[0] == LEVEL_NONE


@pytest.mark.parametrize("with_fng", [False, True])
def test_full_study_runs_and_keeps_the_family_fixed(with_fng: bool) -> None:
    candles = clean_candles(synthetic_candles())
    fng = synthetic_fng(candles)
    panel = build_panel(candles, EntryRules())
    series = fng.set_index("timestamp")["fng_value"].astype("float64") if with_fng else None
    rows = stack_all(model_features(panel, series), outperform_target(panel, "BTC/USDT"), panel.member)
    rules = StudyRules(years=(2022, 2023, 2024, 2025), development_end=pd.Timestamp("2024-12-31", tz=UTC),
                       min_universe=4, top_k=2, boot=BootstrapConfig(n_boot=200, seed=5, ci_level=0.95))
    result = run_study(rows, panel, with_fng, rules)
    levels = result.levels.set_index("model")["level"]
    assert len(levels) == 4
    family = result.tests[~result.tests["model"].eq("MOMENTO_90D")]
    assert len(family) == 8                                          # 4 modelos × 2 hipóteses, sempre
    if not with_fng:
        assert levels["F_LOGIT"] == LEVEL_NOT_RUN and levels["G_GBM"] == LEVEL_NOT_RUN
        assert family.loc[family["model"].eq("F_LOGIT"), "p_holm"].eq(1.0).all()
    assert (family["p_holm"].dropna() >= family["p_value"].dropna().reindex(family["p_holm"].dropna().index).fillna(0)).all()
    run = result.predictive.dropna(subset=["auc"])
    assert run["auc"].between(0, 1).all() and set(run["period"]) <= {"DESENVOLVIMENTO", "TESTE_FINAL"}
