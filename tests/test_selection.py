"""Seleção, score, alocação, arredondamento, orçamento, contrato da recomendação e Telegram. Sem rede."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.transformers.allocation import DECISION_NONE, AllocationRules, allocate
from src.transformers.recommendation import SIGNALS_SCHEMA, build_recommendation, validate_recommendation
from src.transformers.selection import (
    FEATURE_SCHEMA,
    FILTER_OFF,
    FILTER_REDUCE,
    OPP_AVOID,
    OPP_MODERATE,
    OPP_STRONG,
    OPP_WAIT,
    REGIME_DEFENSIVE,
    REGIME_FAVORABLE,
    REGIME_UNAVAILABLE,
    SelectionRules,
    assess,
    compute_features,
    features_on,
    regime_series,
    score_components,
)
from src.transformers.selection_backtest import (
    SELECTION_PERF_SCHEMA,
    STRATEGY_SELECTION,
    evaluate_selection,
    evidence,
    run_weighted,
)
from src.transformers.strategies import market_from_candles
from tests.helpers import make_candles, ramp

RULES = SelectionRules()


def feature_row(**over: Any) -> dict[str, Any]:
    """Uma moeda saudável: tendência, momento, liquidez e risco dentro dos limites."""
    row: dict[str, Any] = {
        "has_candle": True, "close": 110.0, "sma_50": 105.0, "sma_200": 100.0, "history_days": 800, "gap_days_365": 0,
        "avg_volume_30d_usd": 200e6, "ret_7d_pct": 2.0, "ret_30d_pct": 8.0, "ret_90d_pct": 20.0,
        "rel_btc_90d_pct": 5.0, "rel_eth_90d_pct": 3.0, "momentum": 1.0, "vol_90d_pct": 60.0,
        "drawdown_now_pct": -5.0, "drawdown_days": 10, "max_drawdown_180d_pct": -20.0, "stability_50d_pct": 100.0,
        "stretch_50": 0.4, "rsi_14_sel": 60.0, "cost_per_side": 0.0017,
        "setup_sma200": True, "setup_ema_cross": True, "setup_donchian": True, "setup_momentum": True,
        "setup_volume_breakout": False, "setup_pullback": False,
    }
    row.update(over)
    return row


def weak_row(**over: Any) -> dict[str, Any]:
    """Moeda em tendência de baixa (para compor o ranking)."""
    base = feature_row(close=90.0, sma_50=95.0, ret_30d_pct=-10.0, ret_90d_pct=-25.0, momentum=-1.0, stability_50d_pct=0.0,
                       vol_90d_pct=90.0, max_drawdown_180d_pct=-45.0, avg_volume_30d_usd=60e6, setup_sma200=False,
                       setup_ema_cross=False, setup_donchian=False, setup_momentum=False)
    base.update(over)
    return base


def day(rows: dict[str, dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame.from_dict(rows, orient="index")
    frame.index = pd.Index(list(rows), dtype="string", name="symbol")
    return frame.astype(FEATURE_SCHEMA)


def by_symbol(assessed: pd.DataFrame) -> pd.DataFrame:
    return assessed.set_index("symbol")


def universe(**extra: dict[str, Any]) -> pd.DataFrame:
    rows = {"BTC/USDT": weak_row(avg_volume_30d_usd=2e9), "ETH/USDT": weak_row(avg_volume_30d_usd=1e9),
            "ADA/USDT": weak_row(), "XRP/USDT": weak_row()}
    rows.update(extra)
    return day(rows)


# ------------------------------------------------------------------------------ score

def test_components_are_cross_sectional_percentiles_and_score_respects_weights() -> None:
    frame = day({"A": feature_row(momentum=2.0), "B": feature_row(momentum=1.0), "C": feature_row(momentum=0.0)})
    comps = score_components(frame, RULES)
    assert comps["score_momentum"].round(2).tolist() == [83.33, 50.0, 16.67]
    assert comps["score_liquidity"].eq(50.0).all()  # empate: todas no meio
    expected = 0.35 * comps["score_momentum"] + 0.2 * 50 + 0.25 * 50 + 0.2 * 50
    assert np.allclose(comps["score"], expected)
    single = score_components(day({"A": feature_row()}), RULES)
    assert single["score"].iloc[0] == pytest.approx(50.0)  # sozinha não vira 100


def test_unscorable_coin_has_no_score_and_does_not_shift_the_others() -> None:
    frame = day({"A": feature_row(momentum=2.0), "B": feature_row(momentum=1.0), "NEW": feature_row(history_days=100)})
    comps = score_components(frame, RULES)
    assert np.isnan(comps.loc["NEW", "score"])
    assert comps.loc["A", "score_momentum"] == pytest.approx(75.0)


def test_weights_must_sum_to_one_and_have_the_four_components() -> None:
    with pytest.raises(ValueError, match="somando 1"):
        SelectionRules(weights={"momentum": 0.5, "stability": 0.5, "risk": 0.5, "liquidity": 0.0})
    with pytest.raises(ValueError, match="precisa de"):
        SelectionRules(weights={"momentum": 1.0})
    with pytest.raises(ValueError, match="desconhecidas"):
        SelectionRules(setups=("bola_de_cristal",))


# ------------------------------------------------------------------------------ seleção

def test_an_altcoin_with_the_best_evidence_is_selected_not_only_btc_and_eth() -> None:
    out = by_symbol(assess(universe(**{"SOL/USDT": feature_row()}), REGIME_FAVORABLE, RULES))
    assert out.loc["SOL/USDT", "opportunity"] == OPP_STRONG
    assert bool(out.loc["SOL/USDT", "selected"])
    assert not out.loc[["BTC/USDT", "ETH/USDT"], "selected"].any()
    assert any("tendência de alta" in r for r in out.loc["SOL/USDT", "reasons"])


def test_no_good_opportunity_means_no_selection() -> None:
    out = assess(universe(), REGIME_FAVORABLE, RULES)
    assert not out["selected"].any()
    assert out["opportunity"].isin([OPP_WAIT, OPP_AVOID]).all()
    assert all(len(b) > 0 for b in out["blockers"])  # cada descarte diz o que impede a compra


@pytest.mark.parametrize(
    ("over", "word"),
    [
        ({"rsi_14_sel": 20.0, "close": 90.0, "setup_sma200": False, "setup_momentum": False, "ret_90d_pct": -30.0}, "tendência de baixa"),
        ({"ret_7d_pct": 60.0, "close": 95.0, "setup_sma200": False, "ret_90d_pct": -5.0, "setup_momentum": False}, "tendência de baixa"),
        ({"setup_volume_breakout": True, "setup_sma200": False, "setup_ema_cross": False, "setup_donchian": False,
          "close": 98.0}, "tendência de baixa"),
        ({"max_drawdown_180d_pct": -75.0, "drawdown_now_pct": -70.0}, "queda excessiva"),
    ],
    ids=["rsi_baixo", "alta_recente", "volume", "queda_brusca"],
)
def test_an_isolated_signal_never_guarantees_a_buy(over: dict[str, Any], word: str) -> None:
    out = by_symbol(assess(universe(**{"SOL/USDT": feature_row(**over)}), REGIME_FAVORABLE, RULES))
    assert not bool(out.loc["SOL/USDT", "selected"])
    assert any(word in b for b in out.loc["SOL/USDT", "blockers"])


@pytest.mark.parametrize(
    ("over", "opportunity", "word"),
    [
        ({"history_days": 120}, OPP_AVOID, "histórico curto"),
        ({"gap_days_365": 12}, OPP_AVOID, "histórico incompleto"),
        ({"avg_volume_30d_usd": 2e6}, OPP_AVOID, "liquidez baixa"),
        ({"vol_90d_pct": 180.0}, OPP_AVOID, "volatilidade excessiva"),
        ({"has_candle": False}, OPP_AVOID, "sem candle"),
        ({"stretch_50": 2.2, "close": 160.0}, OPP_WAIT, "subiu rápido demais"),
        ({"rsi_14_sel": 88.0}, OPP_WAIT, "sobrecomprada"),
        ({"ret_90d_pct": -2.0}, OPP_WAIT, "momento fraco"),
        ({"setup_ema_cross": False, "setup_donchian": False}, OPP_WAIT, "evidência insuficiente"),
    ],
)
def test_mandatory_filters_block_the_entry_with_a_concrete_reason(over: dict[str, Any], opportunity: str, word: str) -> None:
    out = by_symbol(assess(universe(**{"SOL/USDT": feature_row(**over)}), REGIME_FAVORABLE, RULES))
    assert out.loc["SOL/USDT", "opportunity"] == opportunity
    assert not bool(out.loc["SOL/USDT", "selected"])
    assert any(word in b for b in out.loc["SOL/USDT", "blockers"])


def test_unavailable_data_blocks_even_a_perfect_score() -> None:
    reason = "dado desatualizado: último candle em 10/10/2026 (5 dias de atraso)"
    out = by_symbol(assess(universe(**{"SOL/USDT": feature_row()}), REGIME_FAVORABLE, RULES, unavailable={"SOL/USDT": reason}))
    assert out.loc["SOL/USDT", "opportunity"] == OPP_AVOID
    assert out.loc["SOL/USDT", "blockers"][0] == f"dados indisponíveis: {reason}"


def test_defensive_market_blocks_high_scores_and_other_modes_only_flag_it() -> None:
    rows = universe(**{"SOL/USDT": feature_row()})
    blocked = by_symbol(assess(rows, REGIME_DEFENSIVE, RULES))
    assert blocked.loc["SOL/USDT", "opportunity"] == OPP_WAIT
    assert blocked.loc["SOL/USDT", "score"] > RULES.score_strong  # score alto não passa por cima do filtro de risco
    assert any("mercado defensivo" in b for b in blocked.loc["SOL/USDT", "blockers"])
    for mode in (FILTER_REDUCE, FILTER_OFF):
        flagged = by_symbol(assess(rows, REGIME_DEFENSIVE, replace(RULES, regime_filter=mode)))
        assert flagged.loc["SOL/USDT", "opportunity"] == OPP_MODERATE  # alerta de risco: nunca "boa"
    unavailable = assess(rows, REGIME_UNAVAILABLE, RULES)
    assert not unavailable["selected"].any()


def test_risk_flags_downgrade_to_moderate_and_candidates_are_capped() -> None:
    rows = universe(**{f"C{i}/USDT": feature_row(momentum=1.0 + i / 10) for i in range(6)},
                    **{"HOT/USDT": feature_row(vol_90d_pct=120.0, momentum=3.0)})
    out = by_symbol(assess(rows, REGIME_FAVORABLE, replace(RULES, max_candidates=3)))
    assert out.loc["HOT/USDT", "opportunity"] == OPP_MODERATE
    assert any("volatilidade elevada" in r for r in out.loc["HOT/USDT", "risks"])
    assert int(out["selected"].sum()) == 3
    left_out = out[out["opportunity"].isin([OPP_STRONG, OPP_MODERATE]) & ~out["selected"]]
    assert all(any("fora das 3 melhores" in b for b in bs) for bs in left_out["blockers"])
    ranks = out.loc[out["selected"], "candidate_rank"].tolist()
    assert sorted(ranks) == [1, 2, 3]


# ------------------------------------------------------------------------------ alocação

def selected(rows: dict[str, dict[str, Any]], regime: str = REGIME_FAVORABLE, rules: SelectionRules = RULES) -> pd.DataFrame:
    return assess(universe(**rows), regime, rules)


def test_budget_is_never_exceeded_and_values_are_practical() -> None:
    rng = np.random.default_rng(3)
    for _ in range(40):
        rows = {f"C{i}/USDT": feature_row(vol_90d_pct=float(rng.uniform(25, 140)), momentum=float(rng.normal()))
                for i in range(int(rng.integers(0, 8)))}
        budget = float(rng.choice([0.0, 5.0, 37.0, 100.0, 250.0]))
        alloc, summary = allocate(selected(rows), budget, REGIME_FAVORABLE)
        amounts = alloc["allocation_brl"]
        assert 0.0 <= amounts.sum() <= budget + 1e-9
        assert summary.total_brl == pytest.approx(amounts.sum())
        assert summary.unallocated_brl == pytest.approx(budget - amounts.sum())
        positive = amounts[amounts.gt(0)]
        assert ((positive % 5.0) == 0).all() and positive.ge(10.0).all()
        assert int(amounts.gt(0).sum()) <= 3


def test_no_opportunity_recommends_zero() -> None:
    alloc, summary = allocate(assess(universe(), REGIME_FAVORABLE, RULES), 100.0, REGIME_FAVORABLE)
    assert alloc["allocation_brl"].sum() == 0
    assert summary.decision == DECISION_NONE and summary.unallocated_brl == 100.0


def test_volatility_sizing_gives_less_to_the_riskier_coin_and_caps_per_coin() -> None:
    out = selected({"CALM/USDT": feature_row(vol_90d_pct=40.0), "WILD/USDT": feature_row(vol_90d_pct=85.0)})
    alloc, summary = allocate(out, 100.0, REGIME_FAVORABLE)
    a = alloc.set_index("symbol")["allocation_brl"]
    assert a["CALM/USDT"] == 40.0  # 30% / 40% = 75%, limitado a 40% do orçamento
    assert a["WILD/USDT"] < a["CALM/USDT"]
    assert a["WILD/USDT"] == 35.0  # 30% / 85% = 35,3% -> R$ 35 (arredondado para baixo)
    assert summary.total_brl == 75.0


def test_theoretical_target_above_budget_is_reported_but_capped() -> None:
    rows = {f"C{i}/USDT": feature_row(vol_90d_pct=30.0) for i in range(3)}
    alloc, summary = allocate(selected(rows), 100.0, REGIME_FAVORABLE)
    assert summary.theoretical_total_brl == pytest.approx(120.0)  # 3 × 40%
    assert summary.capped_by_budget and summary.total_brl <= 100.0
    assert any("exposição-alvo" in n for n in summary.notes)
    assert alloc["allocation_brl"].tolist().count(30.0) == 3  # 33,33 cada -> R$ 30


def test_amounts_below_the_minimum_order_are_zeroed_and_explained() -> None:
    out = selected({"SOL/USDT": feature_row(vol_90d_pct=60.0)})
    alloc, summary = allocate(out, 20.0, REGIME_FAVORABLE)  # 40% de R$ 20 = R$ 8 < R$ 10
    row = alloc.set_index("symbol").loc["SOL/USDT"]
    assert row["allocation_brl"] == 0.0 and "ordem mínima" in str(row["allocation_note"])
    assert summary.total_brl == 0.0 and any("nenhum aporte é executável" in n for n in summary.notes)
    _, tiny = allocate(out, 5.0, REGIME_FAVORABLE)
    assert any("abaixo da ordem mínima" in n for n in tiny.notes)  # orçamento insuficiente


def test_fixed_costs_can_make_a_small_order_uneconomic() -> None:
    out = selected({"SOL/USDT": feature_row(vol_90d_pct=60.0)})
    alloc, _ = allocate(out, 100.0, REGIME_FAVORABLE, AllocationRules(fixed_cost=2.0))  # R$ 2 sobre R$ 40 = 5%
    assert alloc["allocation_brl"].sum() == 0.0
    assert "economicamente inviável" in str(alloc["allocation_note"].dropna().iloc[0])


def test_moderate_gets_half_conviction_and_reduce_mode_halves_targets() -> None:
    strong = selected({"SOL/USDT": feature_row(vol_90d_pct=75.0)})
    moderate = selected({"SOL/USDT": feature_row(vol_90d_pct=95.0)})  # volatilidade elevada: moderada
    a_strong, _ = allocate(strong, 100.0, REGIME_FAVORABLE)
    a_mod, _ = allocate(moderate, 100.0, REGIME_FAVORABLE)
    assert a_strong["allocation_brl"].sum() == 40.0
    assert a_mod["allocation_brl"].sum() == 15.0  # 30/95 = 31,6% × 0,5 = R$ 15,79 -> R$ 15
    reduce = replace(RULES, regime_filter=FILTER_REDUCE)
    defensive = selected({"SOL/USDT": feature_row(vol_90d_pct=40.0)}, REGIME_DEFENSIVE, reduce)
    alloc, summary = allocate(defensive, 100.0, REGIME_DEFENSIVE, AllocationRules(regime_filter=FILTER_REDUCE))
    assert alloc["allocation_brl"].sum() == 10.0  # 40% × 0,5 (moderada) × 0,5 (regime)
    assert any("defensivo" in n for n in summary.notes)


def test_max_positions_limits_funded_coins() -> None:
    rows = {f"C{i}/USDT": feature_row(vol_90d_pct=100.0, momentum=1 + i) for i in range(3)}
    alloc, _ = allocate(selected(rows), 100.0, REGIME_FAVORABLE, AllocationRules(max_positions=2))
    assert int(alloc["allocation_brl"].gt(0).sum()) == 2
    assert alloc["allocation_note"].fillna("").str.contains("limite de 2 posições").sum() == 1


def test_invalid_budget_or_rules_are_rejected() -> None:
    out = selected({})
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="orçamento inválido"):
            allocate(out, bad, REGIME_FAVORABLE)
    with pytest.raises(ValueError):
        AllocationRules(round_to=0)
    with pytest.raises(ValueError):
        AllocationRules(max_allocation_pct=1.5)


# ------------------------------------------------------------------------------ indicadores e dados inválidos

def market_candles(n: int = 420) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    series = {
        "BTC/USDT": ramp(50, 150, n),
        "ETH/USDT": list(100 * np.exp(np.cumsum(rng.normal(0.001, 0.03, n)))),
        "NEW/USDT": ramp(10, 20, 60),  # recém-listada
    }
    return make_candles(series, "2026-10-15", quote_volume=80e6)


def test_features_do_not_invent_history_for_a_recent_listing() -> None:
    f = compute_features(market_from_candles(market_candles()))
    today = features_on(f, pd.Timestamp("2026-10-15", tz="UTC"))
    assert int(today.loc["NEW/USDT", "history_days"]) == 60
    assert np.isnan(today.loc["NEW/USDT", "sma_200"]) and np.isnan(today.loc["NEW/USDT", "ret_90d_pct"])
    out = by_symbol(assess(today, REGIME_FAVORABLE, RULES))
    assert out.loc["NEW/USDT", "opportunity"] == OPP_AVOID
    assert any("histórico curto" in b for b in out.loc["NEW/USDT", "blockers"])
    assert np.isnan(out.loc["NEW/USDT", "score"])


def test_invalid_prices_and_gaps_are_not_used_as_signals() -> None:
    candles = market_candles()
    eth = candles["symbol"].eq("ETH/USDT")
    candles.loc[eth & candles["timestamp"].eq(pd.Timestamp("2026-10-15", tz="UTC")), "close"] = -1.0  # preço inválido hoje
    gap = eth & candles["timestamp"].between(pd.Timestamp("2026-06-01", tz="UTC"), pd.Timestamp("2026-06-10", tz="UTC"))
    candles = candles[~gap]
    f = compute_features(market_from_candles(candles))
    today = features_on(f, pd.Timestamp("2026-10-15", tz="UTC"))
    assert not bool(today.loc["ETH/USDT", "has_candle"])
    assert int(today.loc["ETH/USDT", "gap_days_365"]) == 11
    out = by_symbol(assess(today, REGIME_FAVORABLE, RULES))
    assert out.loc["ETH/USDT", "opportunity"] == OPP_AVOID


def test_regime_follows_btc_and_its_sma200() -> None:
    f = compute_features(market_from_candles(market_candles()))
    reg = regime_series(f)
    assert reg.loc[pd.Timestamp("2026-10-15", tz="UTC")] == REGIME_FAVORABLE  # BTC em rampa de alta
    assert reg.iloc[0] == REGIME_UNAVAILABLE  # sem SMA 200 ainda
    down = make_candles({"BTC/USDT": ramp(150, 50, 420)}, "2026-10-15")
    assert regime_series(compute_features(market_from_candles(down))).iloc[-1] == REGIME_DEFENSIVE


# ------------------------------------------------------------------------------ backtest

def test_weighted_engine_applies_weights_from_the_next_day_and_charges_costs() -> None:
    idx = pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC")
    returns = pd.DataFrame({"A": [0.0, 0.10, 0.10, -0.05]}, index=idx)
    cost = pd.DataFrame({"A": [0.01] * 4}, index=idx)
    targets = pd.DataFrame({"A": [1.0]}, index=idx[:1])
    run = run_weighted(targets, returns, cost, idx[0], idx[-1])
    assert run.daily.iloc[0] == 0.0  # decidido no fechamento do dia 1: não ganha o dia 1
    assert run.daily.iloc[1] == pytest.approx(0.99 * 1.10 - 1)  # custo de 1% no primeiro dia investido
    assert run.daily.iloc[2] == pytest.approx(0.10)
    assert run.n_trades == 1 and run.cost == pytest.approx(0.01)
    cash = run_weighted(targets * 0, returns, cost, idx[0], idx[-1])
    assert cash.daily.eq(0).all()


def test_evaluate_selection_produces_every_strategy_and_an_honest_verdict() -> None:
    rng = np.random.default_rng(5)
    n = 900
    series = {s: list(100 * np.exp(np.cumsum(rng.normal(0.0008, 0.03, n)))) for s in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT")}
    f = compute_features(market_from_candles(make_candles(series, "2026-10-15", quote_volume=80e6)))
    periods = {"TREINO": (pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-12-31", tz="UTC")),
               "TESTE": (pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-12-31", tz="UTC"))}
    perf, sel = evaluate_selection(f, regime_series(f), periods, 100.0, 7)
    assert list(perf.columns) == list(SELECTION_PERF_SCHEMA)
    assert len(perf) == 6 * 2
    assert sel.variable.sum(axis=1).le(1.0 + 1e-9).all()  # nunca mais que 100% do orçamento
    text = evidence(perf, "TESTE")
    assert "Sharpe" in text and ("não superou" in text or "superou" in text)
    assert evidence(perf.iloc[0:0], "TESTE").startswith("Sem validação")
    assert STRATEGY_SELECTION in set(perf["strategy"])


# ------------------------------------------------------------------------------ contrato

def contract(rows: dict[str, dict[str, Any]], budget: float = 100.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    assessed = selected(rows)
    alloc, summary = allocate(assessed, budget, REGIME_FAVORABLE)
    ts = pd.Timestamp("2026-10-15", tz="UTC")
    signals = pd.DataFrame({
        "timestamp": ts, "symbol": assessed["symbol"], "close": 100.0, "sma_90": 95.0, "zscore_90": 0.1,
        "sma_200": 90.0, "rsi_14": 55.0, "market_cap_usd": np.nan, "total_volume_usd": np.nan, "fng_value": pd.NA,
        "fng_classification": pd.NA, "regime_up": True, "uptrend": True, "panic": False, "stage": "NEUTRO",
        "stage_reason": pd.NA, "prev_stage": pd.NA, "alert": pd.NA,
    })
    return build_recommendation(
        signals, assessed, alloc, summary, run_ts=pd.Timestamp("2026-10-16 00:10", tz="UTC"), regime=REGIME_FAVORABLE,
        regime_filter="bloquear", regime_symbol="BTC/USDT", excluded=["SUI: histórico curto"], evidence="teste",
        data_notes=[],
    )


def test_contract_has_the_declared_schema_and_passes_validation() -> None:
    sig, rec = contract({"SOL/USDT": feature_row(), "DOT/USDT": feature_row(vol_90d_pct=50.0)})
    assert list(sig.columns) == list(SIGNALS_SCHEMA)
    assert validate_recommendation(sig, rec) == []
    r = rec.iloc[0]
    assert r["total_brl"] == sig["allocation_brl"].sum() and r["unallocated_brl"] == 100.0 - r["total_brl"]
    assert r["n_funded"] == 2 and r["data_status"] == "OK" and list(r["excluded"]) == ["SUI: histórico curto"]


def test_validation_rejects_over_budget_and_unselected_allocations() -> None:
    sig, rec = contract({"SOL/USDT": feature_row()})
    over = sig.copy()
    over.loc[over["symbol"].eq("ADA/USDT"), "allocation_brl"] = 90.0
    problems = validate_recommendation(over, rec)
    assert any("passa do orçamento" in p for p in problems)
    assert any("não selecionada" in p for p in problems)
    stale = sig.copy()
    stale.loc[stale["symbol"].eq("SOL/USDT"), "stage"] = "INDISPONÍVEL"
    assert any("sem dado confiável" in p for p in validate_recommendation(stale, rec))
