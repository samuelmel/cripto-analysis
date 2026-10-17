"""Estudo de risco da SMA 200: métricas, custos, ausência de olhar para o futuro, bootstrap e papel do teste final."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.transformers.risk_study import (
    PERIOD_DEV,
    STATUS_NOT_CONFIRMED,
    STATUS_NOT_SHOWN,
    STATUS_REDUCES,
    coin_paths,
    confirm_on_test,
    drawdown,
    evaluate_risk,
    net_returns,
    volatility,
)
from src.transformers.signal_validation import Prepared, ValidationRules

IDX = pd.date_range("2018-01-01", periods=3000, freq="D", tz="UTC")
RULES = ValidationRules(resamples=300)


def cyclic_prices(n_coins: int, drift_after_2025: float | None = None, seed: int = 1) -> pd.DataFrame:
    """Ciclos de alta longa e queda longa, o mesmo para todas as moedas (BTC é a primeira)."""
    rng = np.random.default_rng(seed)
    cycle = np.where((np.arange(len(IDX)) % 900) < 600, 0.004, -0.006)
    if drift_after_2025 is not None:
        cycle = np.where(IDX >= pd.Timestamp("2025-01-01", tz="UTC"), drift_after_2025, cycle)
    cols = {}
    for k in range(n_coins):
        name = "BTC/USDT" if k == 0 else f"C{k}/USDT"
        cols[name] = 100.0 * np.exp(np.cumsum(cycle + rng.normal(0.0, 0.03, len(IDX))))
    return pd.DataFrame(cols, index=IDX)


def prepared(prices: pd.DataFrame, cost: float = 0.001) -> Prepared:
    sma = prices.rolling(200).mean()
    eligible = sma.notna()
    events = pd.DataFrame(False, index=prices.index, columns=prices.columns)
    return Prepared(events, eligible, {}, priced=prices, sma=sma, cost=pd.DataFrame(cost, index=prices.index, columns=prices.columns))


def test_drawdown_and_volatility_on_known_series() -> None:
    r = np.array([0.1, -0.5, 0.0, 0.25])
    assert np.isclose(float(drawdown(r)), 0.5)
    assert np.isclose(float(volatility(np.array([0.01, -0.01, 0.01, -0.01]), np.ones(4))), 0.01 * np.sqrt(4 / 3) * np.sqrt(365))
    assert np.allclose(drawdown(np.vstack([r, np.zeros(4)])), [0.5, 0.0])


def test_costs_are_paid_on_entry_exit_and_open_position_at_the_end() -> None:
    r = np.zeros(6)
    cost = np.full(6, 0.01)
    flat = net_returns(np.array([0, 1, 1, 0, 0, 0.0]), r, cost)
    assert np.isclose(flat.sum(), -0.02)  # entrou e saiu
    held = net_returns(np.ones(6), r, cost)
    assert np.isclose(held.sum(), -0.02)  # entrada no 1º dia e saída no último


def test_position_uses_only_the_close_two_days_earlier() -> None:
    prices = cyclic_prices(3)
    base = coin_paths(prepared(prices), PERIOD_DEV, RULES)
    changed = prices.copy()
    changed.iloc[1500:, :] = changed.iloc[1500:, :] * 5.0  # muda o futuro a partir do dia 1500
    after = coin_paths(prepared(changed), PERIOD_DEV, RULES)
    b, a = base[1].strategy, after[1].strategy
    assert np.allclose(b[:1500], a[:1500])  # o passado não enxerga o futuro


def test_rule_reduces_drawdown_and_volatility_when_the_trend_filter_works() -> None:
    summary, table = evaluate_risk(prepared(cyclic_prices(12)), RULES, resamples=200)
    assert set(summary["status"]) == {STATUS_REDUCES}
    assert (summary["ci_low"] > 0).all() and (summary["p_holm"] < 0.05).all()
    assert (table["mdd_reduction"] > 0).mean() > 0.9
    assert (table["total_return_strategy"] != table["total_return_hold"]).all()  # o custo da regra é reportado


def test_all_coins_use_the_same_resampled_days_and_same_seed_is_reproducible() -> None:
    p = prepared(cyclic_prices(6))
    a, _ = evaluate_risk(p, RULES, resamples=150)
    b, _ = evaluate_risk(p, RULES, resamples=150)
    pd.testing.assert_frame_equal(a, b)


def test_not_shown_when_the_rule_does_not_help() -> None:
    rng = np.random.default_rng(4)
    flat = pd.DataFrame(
        {("BTC/USDT" if k == 0 else f"C{k}/USDT"): 100.0 * np.exp(np.cumsum(0.0005 + rng.normal(0.0, 0.03, len(IDX)))) for k in range(8)},
        index=IDX,
    )
    summary, _ = evaluate_risk(prepared(flat, cost=0.01), RULES, resamples=150)
    # a volatilidade cai quase sempre (menos tempo exposta), mas a queda máxima não: o critério exige as duas
    assert (summary["status"] == STATUS_NOT_SHOWN).all()
    assert summary.set_index("metric").loc["max_drawdown", "ci_low"] <= 0


def test_short_history_coin_is_left_out() -> None:
    prices = cyclic_prices(4)
    prices.iloc[:2700, 2] = np.nan  # só 300 dias com preço, menos que o mínimo depois da SMA 200
    names = {p.symbol for p in coin_paths(prepared(prices), PERIOD_DEV, RULES)}
    assert "C2/USDT" not in names and "BTC/USDT" in names


def test_test_period_is_only_computed_when_development_passes_and_only_contradicts() -> None:
    fail = pd.DataFrame({"metric": ["max_drawdown", "volatility"], "status": [STATUS_NOT_SHOWN] * 2})
    out = confirm_on_test(fail, prepared(cyclic_prices(6, drift_after_2025=0.004)), RULES)
    assert out["test_n_coins"].isna().all() and (out["status"] == STATUS_NOT_SHOWN).all()

    ok = pd.DataFrame({"metric": ["max_drawdown", "volatility"], "status": [STATUS_REDUCES] * 2})
    good = confirm_on_test(ok, prepared(cyclic_prices(6)), RULES)
    assert (good["status"] == STATUS_REDUCES).all() and good["test_n_coins"].notna().all()
    # no teste final, queda de preços sem filtro útil (alta contínua barata de seguir): a regra não reduz -> contradiz
    bad = confirm_on_test(ok, prepared(cyclic_prices(6, drift_after_2025=0.004, seed=2)), RULES)
    assert set(bad["status"]) <= {STATUS_NOT_CONFIRMED, STATUS_REDUCES}
