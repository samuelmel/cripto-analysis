"""Motor de pesos (`selection_backtest.run_weighted`): guarda de exposição (ENGINE_VERSION 2), caixa parado e moedas sem
preço. Regressões do problema encontrado na auditoria: com a faixa de tolerância, a versão 1 passava de 100% de
exposição ou deixava dinheiro parado. Sem rede."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.selection_backtest import ENGINE_VERSION, run_weighted

DAYS = pd.date_range("2025-01-01", periods=40, freq="D", tz="UTC")
COINS = [f"C{i:02d}/USDT" for i in range(11)]


def frames(returns: float = 0.001) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = pd.DataFrame(returns, index=DAYS, columns=COINS)
    return r, pd.DataFrame(0.0, index=DAYS, columns=COINS)


def targets(rows: dict[int, dict[str, float]]) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=DAYS[list(rows)], columns=COINS)
    for i, weights in rows.items():
        for coin, w in weights.items():
            out.loc[DAYS[i], coin] = w
    return out


def equal(n: int) -> dict[str, float]:
    return {c: 1.0 / n for c in COINS[:n]}


def test_engine_version_is_declared() -> None:
    assert ENGINE_VERSION == "weights-2"


def test_a_new_entry_inside_the_band_no_longer_pushes_exposure_above_the_target() -> None:
    r, c = frames()
    plan = targets({0: equal(10), 7: equal(11)})  # entra uma 11ª moeda: o alvo de todas cai de 10% para 9,09%
    legacy = run_weighted(plan, r, c, DAYS[0], DAYS[-1], guard_exposure=False)
    guarded = run_weighted(plan, r, c, DAYS[0], DAYS[-1])
    assert legacy.exposure.max() > 1.05  # o defeito da versão 1: 10 × 10% mantidos + 9,09% da nova = ~109%
    assert guarded.exposure.max() <= 1.0 + 1e-9
    assert guarded.exposure.iloc[-1] == pytest.approx(1.0)
    assert guarded.turnover > legacy.turnover  # a correção custa um rebalanceamento a mais, e ele é cobrado


def test_cash_from_an_exited_coin_is_reinvested_instead_of_left_idle() -> None:
    r, c = frames()
    plan = targets({0: equal(10), 7: {k: 1.0 / 9 for k in COINS[1:10]}})  # sai a primeira; as outras sobem a 11,1%
    legacy = run_weighted(plan, r, c, DAYS[0], DAYS[-1], guard_exposure=False)
    guarded = run_weighted(plan, r, c, DAYS[0], DAYS[-1])
    assert legacy.exposure.iloc[-1] == pytest.approx(0.9, abs=0.01)  # 10% parados em caixa para sempre
    assert guarded.exposure.iloc[-1] == pytest.approx(1.0, abs=1e-6)


def test_guard_does_not_trade_when_targets_are_stable_or_leak_is_within_the_band() -> None:
    r, c = frames()
    stable = targets({0: equal(10), 7: equal(10), 14: equal(10)})
    run = run_weighted(stable, r, c, DAYS[0], DAYS[-1])
    assert run.turnover == pytest.approx(1.0)  # só a compra inicial
    small = targets({0: equal(10), 7: {**{k: 0.1 for k in COINS[:9]}, COINS[9]: 0.14}})  # 4 p.p. a mais no alvo: cabe na faixa
    kept = run_weighted(small, r, c, DAYS[0], DAYS[-1])
    assert kept.turnover == pytest.approx(1.0)  # mantém tudo: o alvo (104%) não é ultrapassado e a folga é < faixa
    assert kept.exposure.iloc[-1] == pytest.approx(1.0, abs=1e-6)
    trim = targets({0: equal(10), 7: {**{k: 0.1 for k in COINS[:9]}, COINS[9]: 0.06}})  # alvo total 96%: manter ultrapassaria
    assert run_weighted(trim, r, c, DAYS[0], DAYS[-1]).turnover == pytest.approx(1.04)  # a guarda aparou os 4 p.p.


def test_exposure_never_exceeds_the_target_total_over_many_rebalances() -> None:
    rng = np.random.default_rng(5)
    r = pd.DataFrame(0.02 * rng.standard_normal((40, 11)), index=DAYS, columns=COINS)
    c = pd.DataFrame(0.001, index=DAYS, columns=COINS)
    plan = targets({i: equal(int(rng.integers(5, 12))) for i in range(0, 40, 4)})
    run = run_weighted(plan, r, c, DAYS[0], DAYS[-1])
    assert run.exposure.max() <= 1.0 + 1e-9
    assert (run.daily > -1).all() and run.cost > 0


def test_without_a_band_both_engine_versions_agree() -> None:
    r, c = frames()
    plan = targets({0: equal(10), 7: equal(11)})
    a = run_weighted(plan, r, c, DAYS[0], DAYS[-1], band=0.0, guard_exposure=False)
    b = run_weighted(plan, r, c, DAYS[0], DAYS[-1], band=0.0)
    pd.testing.assert_series_equal(a.daily, b.daily)


def test_held_coin_without_a_price_is_counted_not_silently_hidden() -> None:
    r, c = frames()
    r.loc[DAYS[10:20], COINS[0]] = np.nan
    plan = targets({0: equal(10)})
    run = run_weighted(plan, r, c, DAYS[0], DAYS[-1])
    assert run.stale_weight_days == pytest.approx(10 * 0.1, rel=0.05)  # 10 dias com ~10% da carteira sem preço
    clean = run_weighted(plan, frames()[0], c, DAYS[0], DAYS[-1])
    assert clean.stale_weight_days == 0.0
