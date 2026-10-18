"""Estudo dos sinais de entrada: referência por tipo de sinal, níveis, teste final que só rebaixa e comparação pareada."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.entry_signals import KIND_CROSS, KIND_TIMING
from src.transformers.entry_study import (
    HOLDOUT_CONTRADICTED,
    HOLDOUT_INSUFFICIENT,
    HOLDOUT_NOT_ASSESSED,
    HOLDOUT_NOT_CONTRADICTED,
    LEVEL_NO_EVIDENCE,
    LEVEL_PROMISING,
    LEVEL_VALIDATED,
    ComboSpec,
    apply_holm,
    final_level,
    holdout_verdict,
    levels,
    paired_difference,
    signal_table,
    stats_rows,
)
from src.transformers.signal_validation import ValidationRules

RULES = ValidationRules(development_end="2021-12-31", holdout_start="2022-01-01", resamples=200)
IDX = pd.date_range("2021-01-01", periods=60, freq="D", tz="UTC")


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    forward = pd.DataFrame({"X": np.linspace(0.0, 0.59, 60), "Y": 0.10}, index=IDX)
    events = pd.DataFrame(False, index=IDX, columns=["X", "Y"])
    events.loc[IDX[[0, 3, 10]], "X"] = True
    calculable = pd.DataFrame(True, index=IDX, columns=["X", "Y"])
    reference = pd.Series(0.05, index=IDX)
    return events, calculable, forward, reference


def test_selecao_usa_a_media_do_universo_no_mesmo_dia() -> None:
    events, calculable, forward, reference = _frames()
    t = signal_table(events, calculable, forward, reference, KIND_CROSS, 7, "DESENVOLVIMENTO", RULES)
    assert t["day"].tolist() == [IDX[0], IDX[10]]       # IDX[3] a menos de 7 dias do anterior: não independente
    assert t["baseline"].tolist() == pytest.approx([0.05, 0.05])
    assert t["excess"].tolist() == pytest.approx([0.0 - 0.05, 0.10 - 0.05])


def test_tempo_usa_a_media_da_mesma_moeda() -> None:
    events, calculable, forward, reference = _frames()
    t = signal_table(events, calculable, forward, reference, KIND_TIMING, 7, "DESENVOLVIMENTO", RULES)
    assert t["baseline"].iloc[0] == pytest.approx(float(forward["X"].mean()))
    calculable.loc[IDX[30]:, "X"] = False                # só os dias calculáveis entram na referência
    t2 = signal_table(events, calculable, forward, reference, KIND_TIMING, 7, "DESENVOLVIMENTO", RULES)
    assert t2["baseline"].iloc[0] == pytest.approx(float(forward["X"].iloc[:30].mean()))


def test_tipo_desconhecido_e_erro() -> None:
    events, calculable, forward, reference = _frames()
    with pytest.raises(ValueError):
        signal_table(events, calculable, forward, reference, "OUTRO", 7, "DESENVOLVIMENTO", RULES)


def test_holm_sobre_a_familia_inteira() -> None:
    frame = pd.DataFrame({"p_value": [0.01, 0.02, float("nan"), 0.04]})
    adj = apply_holm(frame)["p_holm"].tolist()
    assert adj[0] == pytest.approx(0.04)
    assert adj[2] == pytest.approx(1.0)


def _stats(excess7: float, excess30: float, p: float, ci_low: float) -> pd.DataFrame:
    rows = []
    for h, ex in ((7, excess7), (30, excess30)):
        rows.append({"combo": "A_30", "candidate": "A", "kind": KIND_CROSS, "horizon": h, "excess": ex,
                     "ci_low": ci_low, "ci_high": ex + 0.05, "p_holm": p, "stable_halves": True, "n_signals": 100})
    return pd.DataFrame(rows)


def test_niveis_no_desenvolvimento() -> None:
    hold_ok = {("A_30", 7): (30, 0.01), ("A_30", 30): (25, 0.02)}
    v = levels(_stats(0.03, 0.08, 0.001, 0.01), hold_ok, (7, 30), 0.05)
    assert v["level"].iloc[0] == LEVEL_VALIDATED and v["holdout"].iloc[0] == HOLDOUT_NOT_CONTRADICTED
    p = levels(_stats(0.01, 0.02, 0.6, -0.02), hold_ok, (7, 30), 0.05)
    assert p["level"].iloc[0] == LEVEL_PROMISING
    n = levels(_stats(0.01, -0.02, 0.6, -0.02), {}, (7, 30), 0.05)
    assert n["level"].iloc[0] == LEVEL_NO_EVIDENCE and n["holdout"].iloc[0] == HOLDOUT_NOT_ASSESSED


def test_teste_final_so_rebaixa() -> None:
    contradicted = {("A_30", 7): (40, -0.01), ("A_30", 30): (25, 0.02)}
    v = levels(_stats(0.03, 0.08, 0.001, 0.01), contradicted, (7, 30), 0.05)
    assert v["dev_level"].iloc[0] == LEVEL_VALIDATED and v["level"].iloc[0] == LEVEL_NO_EVIDENCE
    p = levels(_stats(0.01, 0.02, 0.6, -0.02), contradicted, (7, 30), 0.05)
    assert p["level"].iloc[0] == LEVEL_NO_EVIDENCE
    few = {("A_30", 7): (12, -0.5), ("A_30", 30): (8, -0.5)}
    v2 = levels(_stats(0.03, 0.08, 0.001, 0.01), few, (7, 30), 0.05)
    assert v2["level"].iloc[0] == LEVEL_VALIDATED and v2["holdout"].iloc[0] == HOLDOUT_INSUFFICIENT
    assert "não confirmado" in str(v2["reason"].iloc[0])


def test_veredito_do_teste_final() -> None:
    assert holdout_verdict({7: (20, -0.001), 30: (3, 0.5)}) == HOLDOUT_CONTRADICTED
    assert holdout_verdict({7: (19, -0.5), 30: (19, -0.5)}) == HOLDOUT_INSUFFICIENT
    assert holdout_verdict({7: (20, 0.0), 30: (21, 0.1)}) == HOLDOUT_NOT_CONTRADICTED
    assert final_level(LEVEL_NO_EVIDENCE, HOLDOUT_CONTRADICTED) == LEVEL_NO_EVIDENCE
    assert final_level(LEVEL_PROMISING, HOLDOUT_NOT_CONTRADICTED) == LEVEL_PROMISING


def test_estatistica_por_combinacao_e_deterministica() -> None:
    rng = np.random.default_rng(0)
    days = pd.date_range("2020-01-01", periods=300, freq="D", tz="UTC")
    table = pd.DataFrame({"symbol": "X", "day": days, "ret": 0.0, "baseline": 0.0,
                          "excess": rng.normal(0.02, 0.05, 300)}).astype({"symbol": "string"})
    specs = {"C": ComboSpec("C", "C", KIND_TIMING)}
    a = stats_rows({("C", 7): table}, specs, "ABERTURA", RULES)
    b = stats_rows({("C", 7): table}, specs, "ABERTURA", RULES)
    pd.testing.assert_frame_equal(a, b)
    assert a["n_clusters"].iloc[0] == 10 and a["ci_low"].iloc[0] > 0


def test_diferenca_pareada() -> None:
    days = pd.date_range("2020-01-01", periods=120, freq="D", tz="UTC")
    a = pd.DataFrame({"symbol": "X", "day": days, "excess": np.linspace(-0.1, 0.1, 120)})
    same = paired_difference(a, a, days[0], 1, 300)
    assert same.difference == pytest.approx(0.0) and same.ci_low == pytest.approx(0.0) and same.ci_high == pytest.approx(0.0)
    better = paired_difference(a.assign(excess=a["excess"] + 0.05), a, days[0], 1, 300)
    assert better.difference == pytest.approx(0.05) and better.ci_low == pytest.approx(0.05)
    empty = paired_difference(a.iloc[:0], a, days[0], 1, 300)
    assert np.isnan(empty.difference)
