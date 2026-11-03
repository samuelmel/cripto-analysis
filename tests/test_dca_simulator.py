"""Simulador de Smart DCA: execução na abertura seguinte, caixa finito, multiplicadores."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research"))
import dca_simulator as ds  # noqa: E402


def _px(close: list[float], open_: list[float] | None = None, start: str = "2020-01-05") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(close), freq="D", tz="UTC")   # 2020-01-05 é domingo
    return pd.DataFrame({"open": open_ if open_ is not None else close, "close": close}, index=idx)


def test_multiplier_tiers() -> None:
    assert ds.multiplier(0.0) == 1.0 and ds.multiplier(-0.19) == 1.0
    assert ds.multiplier(-0.20) == 3.0 and ds.multiplier(-0.39) == 3.0
    assert ds.multiplier(-0.40) == 5.0 and ds.multiplier(-0.9) == 5.0


def test_fixed_flat_price_pays_only_cost_and_never_holds_cash() -> None:
    px = _px([100.0] * 60)
    o = ds.simulate(px, px["close"].cummax(), px.index[0], px.index[-1], ds.FIXED)
    assert o.value_per_real == pytest.approx(1 / (1 + ds.COST))
    assert o.idle_cash_pct == 0.0 and o.deployed_pct == pytest.approx(100.0)


def test_execution_uses_next_day_open_not_decision_close() -> None:
    close = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]   # domingos: dias 0 e 7
    open_ = [100.0, 200.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 50.0]    # abertura de segunda do dia 0 é 200; do dia 7 é 50
    px = _px(close, open_)
    o = ds.simulate(px, px["close"].cummax(), px.index[0], px.index[-1], ds.FIXED)
    expected_units = 100.0 / (200.0 * (1 + ds.COST)) + 100.0 / (50.0 * (1 + ds.COST))
    assert o.units == pytest.approx(expected_units)


def test_smart_never_spends_more_than_the_vault() -> None:
    close = list(np.linspace(100.0, 20.0, 400))                               # queda contínua de 80%: multiplicador 5x quase todo o tempo
    px = _px(close)
    o = ds.simulate(px, px["close"].cummax(), px.index[0], px.index[-1], ds.SMART, f=0.5)
    assert o.deployed_pct <= 100.0 + 1e-9 and o.idle_cash_pct >= 0.0


def test_smart_at_all_time_highs_keeps_half_in_cash() -> None:
    close = list(np.linspace(100.0, 200.0, 200))                              # sempre na máxima: 1x o lote-base (f=0,5)
    px = _px(close)
    o = ds.simulate(px, px["close"].cummax(), px.index[0], px.index[-1], ds.SMART, f=0.5)
    assert o.deployed_pct == pytest.approx(50.0, abs=0.5)


def test_isolation_rescales_to_same_total_spend() -> None:
    close = list(np.r_[np.linspace(100, 50, 150), np.linspace(50, 120, 150)])
    px = _px(close)
    ath = px["close"].cummax()
    fixed = ds.simulate(px, ath, px.index[0], px.index[-1], ds.FIXED)
    avg, value = ds.isolate_infinite_cash(px, ath, px.index[0], px.index[-1], fixed)
    assert avg > 0 and value > 0
