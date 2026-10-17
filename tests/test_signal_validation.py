"""Validação estatística do COMPRAR: universo point-in-time, ausência de look-ahead, reprodutibilidade e poder."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.signal_validation import (
    HOLDOUT_CONFIRMED,
    HOLDOUT_INSUFFICIENT,
    HOLDOUT_REFUTED,
    STATUS_NO_EVIDENCE,
    STATUS_NOT_VALIDATED,
    STATUS_REVOKED,
    STATUS_VALIDATED,
    Prepared,
    ValidationRules,
    apply_evidence_to_stage,
    apply_holdout,
    count_independent,
    evaluate_development,
    excess_stats,
    independent_positions,
    prepare,
    stable_seed,
)
from src.transformers.stats import holm_adjust
from src.transformers.universe_pit import PitRules, candidate_symbols, membership, universe_on
from tests.helpers import make_candles

RULES = ValidationRules(n_min=15)


# ------------------------------------------------------------------------------------------ universo point-in-time

def market() -> pd.DataFrame:
    n = 700
    rng = np.random.default_rng(0)
    closes = {s: list(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))) for s in ("BTC/USDT", "ETH/USDT", "OLD/USDT")}
    candles = make_candles(closes, "2026-06-30")
    # OLD deixa de negociar no dia 500 (deslistada); NEW só aparece no dia 600 com volume enorme
    first = candles["timestamp"].min()
    candles = candles[~(candles["symbol"].eq("OLD/USDT") & candles["timestamp"].gt(first + pd.Timedelta(days=500)))]
    new = make_candles({"NEW/USDT": list(np.linspace(1, 2, 100))}, "2026-06-30", quote_volume=9e9)
    return pd.concat([candles, new], ignore_index=True)


def test_universe_of_a_day_ignores_the_future_and_keeps_delisted_coins_in_the_past() -> None:
    candles = market()
    first = candles["timestamp"].min()
    day = first + pd.Timedelta(days=450)
    full = universe_on(candles, day)
    cut = universe_on(candles[candles["timestamp"].le(day)], day)
    assert full == cut  # truncagem: cortar o futuro não muda o universo de D
    assert "OLD/USDT" in full and "NEW/USDT" not in full
    later = universe_on(candles, first + pd.Timedelta(days=650))
    assert "OLD/USDT" not in later  # parou de negociar: sai
    assert "NEW/USDT" not in universe_on(candles, first + pd.Timedelta(days=620))  # sem histórico mínimo ainda


def test_membership_rows_do_not_change_when_later_data_is_removed() -> None:
    candles = market()
    day = candles["timestamp"].min() + pd.Timedelta(days=480)
    a = membership(candles).loc[:day]
    b = membership(candles[candles["timestamp"].le(day)]).loc[:day]
    cols = sorted(set(a.columns) & set(b.columns))
    pd.testing.assert_frame_equal(a[cols], b[cols])
    assert set(a.columns) - set(b.columns) <= {"NEW/USDT"}  # a moeda que só existe no futuro nem aparece no corte


def test_name_rules_drop_stablecoins_fiat_and_leveraged_tokens() -> None:
    kept = candidate_symbols(["BTC/USDT", "USDC/USDT", "EUR/USDT", "BTCUP/USDT", "BTCDOWN/USDT", "ETH/USDT"], PitRules())
    assert kept == ("BTC/USDT", "ETH/USDT")


def test_size_cap_keeps_the_most_liquid_of_the_day() -> None:
    candles = pd.concat(
        [make_candles({f"C{i}/USDT": [10.0] * 400}, "2026-06-30", quote_volume=2e6 * (i + 1)) for i in range(5)],
        ignore_index=True,
    )
    day = candles["timestamp"].max()
    assert universe_on(candles, day, PitRules(max_size=2)) == ("C3/USDT", "C4/USDT")


# --------------------------------------------------------------------------------------------- sem look-ahead

def trending_market() -> pd.DataFrame:
    n = 900
    rng = np.random.default_rng(3)
    closes = {s: list(100 * np.exp(np.cumsum(rng.normal(0.001, 0.03, n)))) for s in ("BTC/USDT", "ETH/USDT", "SOL/USDT")}
    return make_candles(closes, "2026-06-30")


def test_events_and_eligibility_use_only_the_past() -> None:
    candles = trending_market()
    cut = candles["timestamp"].min() + pd.Timedelta(days=600)
    full = prepare(candles, RULES)
    part = prepare(candles[candles["timestamp"].le(cut)], RULES)
    for name in ("events", "eligible"):
        a, b = getattr(full, name).loc[:cut], getattr(part, name).loc[:cut]
        pd.testing.assert_frame_equal(a, b)


def test_forward_return_enters_at_the_next_close_with_costs() -> None:
    candles = trending_market()
    prep = prepare(candles, RULES)
    px = candles.pivot(index="timestamp", columns="symbol", values="close")
    t = px.index[400]
    h = 7
    gross = px.loc[px.index[401 + h], "ETH/USDT"] / px.loc[px.index[401], "ETH/USDT"]
    got = prep.forward[h].loc[t, "ETH/USDT"]
    assert 1.0 + got < gross  # custos pagos nos dois lados
    assert 1.0 + got > gross * 0.97  # e de ordem de grandeza razoável (taxa + spread + slippage)


def test_independent_signals_are_not_overlapping() -> None:
    kept = independent_positions(np.array([0, 3, 7, 8, 14, 30]), 7)
    assert kept.tolist() == [0, 7, 14, 30]
    counts = count_independent(prepare(trending_market(), RULES), RULES)
    assert (counts["n_independent"] <= counts["n_events"]).all()


# ------------------------------------------------------------------------------- estatística: semente, poder, tipo I

def rules_small() -> ValidationRules:
    return ValidationRules(n_min=15, null_draws=4000, resamples=500)


def test_same_seed_gives_the_same_interval_and_other_seed_does_not() -> None:
    rng = np.random.default_rng(1)
    base = rng.normal(0.0, 0.05, 1500)
    sig = rng.normal(0.02, 0.05, 30)
    r = rules_small()
    a = excess_stats(sig, sig, base, 7, 123, r)
    b = excess_stats(sig, sig, base, 7, 123, r)
    c = excess_stats(sig, sig, base, 7, 124, r)
    assert (a.ci_low, a.ci_high, a.p_value) == (b.ci_low, b.ci_high, b.p_value)
    assert (a.ci_low, a.p_value) != (c.ci_low, c.p_value)
    assert stable_seed(5, "A", 7) == stable_seed(5, "A", 7) != stable_seed(5, "B", 7)


def test_injected_effect_is_detected() -> None:
    rng = np.random.default_rng(2)
    base = rng.normal(0.0, 0.05, 2000)
    sig = rng.normal(0.05, 0.05, 40)  # +5 p.p. de vantagem real
    s = excess_stats(sig, sig, base, 7, 9, rules_small())
    assert s.excess > 0.03 and s.p_value < 0.01 and s.ci_low > 0


def test_random_signals_are_rejected_after_holm() -> None:
    """Sinais sorteados da própria referência (sem vantagem) em 60 moedas: nenhuma passa pelo critério com Holm."""
    r = rules_small()
    p_values, ci_lows = [], []
    for k in range(60):
        rng = np.random.default_rng(100 + k)
        base = rng.normal(0.0, 0.05, 2000)
        sig = rng.choice(base, 30)
        s = excess_stats(sig, sig, base, 7, 1000 + k, r)
        p_values.append(s.p_value)
        ci_lows.append(s.ci_low)
    assert min(holm_adjust(p_values)) >= 0.05
    assert sum(c > 0 for c in ci_lows) <= 8  # o IC sozinho erraria ~2,5% das vezes; Holm é o que protege


# ------------------------------------------------------------------------- status e papel do hold-out (Prepared sintético)

IDX = pd.date_range("2020-01-01", "2026-06-30", freq="D", tz="UTC")
HOLD0 = int(IDX.searchsorted(pd.Timestamp("2025-01-01", tz="UTC")))


def synthetic(spec: dict[str, tuple[float, int, float, int]]) -> Prepared:
    """Moeda -> (efeito no desenvolvimento, nº de sinais, efeito no hold-out, nº de sinais no hold-out)."""
    events = pd.DataFrame(False, index=IDX, columns=list(spec))
    eligible = pd.DataFrame(True, index=IDX, columns=list(spec))
    forward = {h: pd.DataFrame(0.0, index=IDX, columns=list(spec)) for h in (7, 30)}
    for k, (symbol, (dev_eff, n_dev, hold_eff, n_hold)) in enumerate(spec.items()):
        rng = np.random.default_rng(50 + k)
        for h in (7, 30):
            forward[h][symbol] = rng.normal(0.0, 0.05, len(IDX))
        for j in range(n_dev):
            pos = 100 + 40 * j
            events.iloc[pos, k] = True
            for h in (7, 30):
                forward[h].iloc[pos, k] += dev_eff
        for j in range(n_hold):
            pos = HOLD0 + 20 + 40 * j
            events.iloc[pos, k] = True
            for h in (7, 30):
                forward[h].iloc[pos, k] += hold_eff
    return Prepared(events, eligible, forward)


def test_status_validated_not_validated_and_no_evidence() -> None:
    spec = {"GOOD/USDT": (0.12, 30, 0.12, 8), "FEW/USDT": (0.12, 6, 0.0, 0)}
    spec.update({f"N{i}/USDT": (0.0, 30, 0.0, 0) for i in range(8)})
    _, summary = evaluate_development(synthetic(spec), rules_small())
    status = dict(zip(summary["symbol"], summary["status"], strict=True))
    assert status["GOOD/USDT"] == STATUS_VALIDATED
    assert status["FEW/USDT"] == STATUS_NO_EVIDENCE  # poucos sinais: nunca "boa"
    assert all(status[f"N{i}/USDT"] == STATUS_NOT_VALIDATED for i in range(8))


def test_holdout_only_revokes_and_never_grants() -> None:
    spec = {
        "KEEP/USDT": (0.12, 30, 0.10, 8),      # passa e confirma
        "FLOP/USDT": (0.12, 30, -0.10, 8),     # passa, mas o teste final é negativo com sinais suficientes
        "THIN/USDT": (0.12, 30, -0.10, 2),     # passa; poucos sinais no teste final: nem refuta nem confirma
        "LUCKY/USDT": (0.0, 30, 0.30, 8),      # não passou no desenvolvimento: o hold-out não promove
    }
    spec.update({f"N{i}/USDT": (0.0, 30, 0.0, 0) for i in range(6)})
    prep = synthetic(spec)
    _, dev = evaluate_development(prep, rules_small())
    final, _ = apply_holdout(dev, prep, rules_small())
    by = final.set_index("symbol")
    assert by.loc["KEEP/USDT", "status"] == STATUS_VALIDATED and by.loc["KEEP/USDT", "holdout"] == HOLDOUT_CONFIRMED
    assert by.loc["FLOP/USDT", "status"] == STATUS_REVOKED and by.loc["FLOP/USDT", "holdout"] == HOLDOUT_REFUTED
    assert by.loc["THIN/USDT", "status"] == STATUS_VALIDATED and by.loc["THIN/USDT", "holdout"] == HOLDOUT_INSUFFICIENT
    assert by.loc["LUCKY/USDT", "status"] == STATUS_NOT_VALIDATED


def test_development_window_never_reads_the_holdout() -> None:
    """Um efeito enorme só no hold-out não muda o veredito do desenvolvimento (expurgo de janelas)."""
    base = {f"N{i}/USDT": (0.0, 30, 0.0, 0) for i in range(8)}
    a = evaluate_development(synthetic({**base, "X/USDT": (0.0, 30, 0.0, 8)}), rules_small())[1]
    b = evaluate_development(synthetic({**base, "X/USDT": (0.0, 30, 5.0, 8)}), rules_small())[1]
    pd.testing.assert_frame_equal(a, b)


# ------------------------------------------------------------------------------------------------ gating do estágio

def test_only_validated_coins_keep_the_buy_stage() -> None:
    evidence = pd.DataFrame({"symbol": ["BTC/USDT", "ETH/USDT"], "status": [STATUS_VALIDATED, STATUS_NOT_VALIDATED]})
    frame = pd.DataFrame(
        {"symbol": ["BTC/USDT", "ETH/USDT", "SOL/USDT"], "stage": ["COMPRAR", "COMPRAR", "PREPARAR"]}
    )
    out = apply_evidence_to_stage(frame, evidence, ("COMPRAR", "PREPARAR"))
    assert out["stage"].tolist() == ["COMPRAR", "NEUTRO", "NEUTRO"]
    closed = apply_evidence_to_stage(frame, evidence.iloc[0:0], ("COMPRAR", "PREPARAR"))
    assert closed["stage"].tolist() == ["NEUTRO"] * 3  # sem evidência publicada: falha fechada
