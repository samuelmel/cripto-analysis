"""Laboratório de estratégias: sinais sem lookahead, DCA, operações, referência aleatória e protocolo de escolha."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research"))

import lab  # noqa: E402
import strategy_lab  # noqa: E402

from src.transformers.anomaly_detector import classify_history  # noqa: E402
from src.transformers.trade_simulator import evaluate_portfolio, run_portfolio  # noqa: E402
from tests.helpers import make_candles  # noqa: E402

FEE = 0.001


def market(closes: dict[str, list[float]], volume: float = 1_000_000.0) -> lab.Market:
    candles = make_candles(closes, "2026-06-30", quote_volume=volume)
    return lab.market_from_candles(candles)


def frame(values: dict[str, list[float]]) -> pd.DataFrame:
    n = len(next(iter(values.values())))
    return pd.DataFrame(values, index=pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC"))


def test_latch_exit_wins_on_the_same_day() -> None:
    entry = frame({"A": [0, 1, 0, 1, 1]}).astype(bool)
    exit_ = frame({"A": [0, 0, 0, 1, 0]}).astype(bool)
    assert lab.latch(entry, exit_)["A"].tolist() == [0.0, 1.0, 1.0, 0.0, 1.0]


def test_donchian_enters_on_breakout_and_leaves_below_the_channel() -> None:
    closes = [10.0] * 30 + [12.0, 12.5, 12.0, 8.0, 8.0]
    pos = lab.donchian_breakout(market({"A/USDT": closes}), n=20)["A/USDT"].to_numpy()
    assert pos[29] == 0 and pos[30] == 1  # rompeu a máxima dos 20 dias anteriores
    assert pos[33] == 0  # fechou abaixo da mínima dos 10 dias anteriores


@pytest.mark.parametrize("signal", ["donchian", "bollinger", "rsi", "volume"])
def test_signals_have_no_lookahead(signal: str) -> None:
    rng = np.random.default_rng(1)
    base = list(100 * np.exp(np.cumsum(rng.standard_normal(300) * 0.02)))
    changed = base[:200] + [x * 3 for x in base[200:]]  # futuro diferente depois do dia 199
    fns = {
        "donchian": lambda m: lab.donchian_breakout(m, 20),
        "bollinger": lambda m: lab.bollinger_reversion(m, 20, 2.0),
        "rsi": lambda m: lab.rsi_oversold(m, 30, 50),
        "volume": lambda m: lab.volume_breakout(m, 20, 1.0),
    }
    a = fns[signal](market({"A/USDT": base}))["A/USDT"].to_numpy()
    b = fns[signal](market({"A/USDT": changed}))["A/USDT"].to_numpy()
    assert a[:200].tolist() == b[:200].tolist()


def test_volume_breakout_needs_the_volume_confirmation() -> None:
    closes = [10.0] * 30 + [12.0] + [12.0] * 5
    candles = make_candles({"A/USDT": closes}, "2026-06-30", quote_volume=1_000_000.0)
    quiet = lab.market_from_candles(candles)
    assert lab.volume_breakout(quiet, 20, 1.5)["A/USDT"].iloc[30] == 0.0
    candles.loc[candles.index[30], "quote_volume"] = 5_000_000.0
    loud = lab.market_from_candles(candles)
    assert lab.volume_breakout(loud, 20, 1.5)["A/USDT"].iloc[30] == 1.0


def test_rsi_bounds() -> None:
    r = lab.rsi(market({"A/USDT": list(100 + np.sin(np.arange(200)) * 5 + np.arange(200) * 0.1)}).close)
    assert r.dropna().ge(0).all().all() and r.dropna().le(100).all().all()


def test_engine_matches_a_hand_computed_portfolio() -> None:
    returns = frame({"A": [np.nan, 0.10, -0.05, 0.02]})
    valid = frame({"A": [True, True, True, True]})
    positions = frame({"A": [0.0, 1.0, 1.0, 0.0]})  # compra no fechamento do dia 1, vende no do dia 3
    run = run_portfolio(positions, returns, valid, returns.index[0], returns.index[-1], FEE)
    assert np.isnan(run.held["A"].iloc[0])
    # dia 2: a compra decidida no dia 1 rende -5% e paga a taxa; dia 3: rende +2%; a venda decidida no dia 3
    # só paga a taxa no dia 4, fora da janela.
    assert run.daily.iloc[2] == pytest.approx(-0.05 - FEE)
    assert run.daily.iloc[3] == pytest.approx(0.02)
    metrics = evaluate_portfolio(positions, returns, valid, returns.index[0], returns.index[-1], FEE)
    assert metrics["total"] == pytest.approx(((1 - 0.05 - FEE) * 1.02 - 1) * 100.0)


def test_trade_stats_for_one_winning_trade() -> None:
    returns = frame({"A": [0.0, 0.0, 0.5, 0.2, 0.0, 0.0]})
    valid = frame({"A": [True] * 6})
    positions = frame({"A": [0.0, 1.0, 1.0, 0.0, 0.0, 0.0]})
    run = run_portfolio(positions, returns, valid, returns.index[0], returns.index[-1], FEE)
    trades = lab.trade_returns(run, FEE)
    assert len(trades) == 1
    assert trades.iloc[0] == pytest.approx(1.5 * 1.2 * (1 - FEE) ** 2 - 1)
    m = lab.lab_metrics(run, FEE)
    assert m["n_trades"] == 1 and m["win_rate"] == 100.0 and m["profit_factor"] == float("inf")
    assert m["fee_cost"] > 0


def test_open_trade_pays_only_the_entry_fee() -> None:
    returns = frame({"A": [0.0, 0.0, 0.1, 0.1]})
    valid = frame({"A": [True] * 4})
    positions = frame({"A": [0.0, 1.0, 1.0, 1.0]})
    run = run_portfolio(positions, returns, valid, returns.index[0], returns.index[-1], FEE)
    assert lab.trade_returns(run, FEE).iloc[0] == pytest.approx(1.1 * 1.1 * (1 - FEE) - 1)


def test_dca_counts_purchases_and_costs() -> None:
    close = frame({"A": [100.0] * 30})
    valid = frame({"A": [True] * 30})
    run, lots = lab.dca_run(close, valid, close.index[0], close.index[-1], every=7, fee=FEE)
    assert len(lots) == 5  # dias 0, 7, 14, 21 e 28
    assert (1 + run.daily).prod() - 1 == pytest.approx(-FEE)  # preço parado: só a taxa de entrada de cada aporte
    assert lab.lab_metrics(run, FEE, lots)["n_trades"] == 5


def test_random_reference_keeps_exposure_and_uses_fixed_seeds() -> None:
    rng = np.random.default_rng(2)
    n = 400
    returns = frame({"A": list(rng.standard_normal(n) * 0.02), "B": list(rng.standard_normal(n) * 0.02)})
    valid = frame({"A": [True] * n, "B": [True] * n})
    positions = frame({"A": ([1.0] * 30 + [0.0] * 70) * 4, "B": ([0.0] * 50 + [1.0] * 50) * 4})
    start, end = returns.index[0], returns.index[-1]

    shifted = lab.shifted_positions(positions, valid, np.random.default_rng(5))
    assert shifted.sum().tolist() == positions.sum().tolist()  # mesma exposição, dia a dia somada
    assert not shifted.equals(positions)

    a = lab.random_reference(positions, returns, valid, start, end, FEE, sims=8, first_seed=100)
    b = lab.random_reference(positions, returns, valid, start, end, FEE, sims=8, first_seed=100)
    pd.testing.assert_frame_equal(a, b)
    c = lab.random_reference(positions, returns, valid, start, end, FEE, sims=8, first_seed=200)
    assert not a.equals(c)
    # A exposição decidida é a mesma em todos os sorteios; o tempo comprado medido só varia pelo dia perdido no
    # deslocamento "decide em t, rende em t+1" (no máximo ~1 dia em 400).
    assert a["invested"].max() - a["invested"].min() < 0.5
    assert abs(a["invested"].mean() - 100 * positions.mean().mean()) < 0.5


def _synthetic_market(days: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    series = {s: list(100 * np.exp(np.cumsum(rng.standard_normal(days) * 0.03))) for s in ("BTC/USDT", "ETH/USDT")}
    return make_candles(series, "2026-06-30")


def test_parameters_are_never_chosen_with_test_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(strategy_lab, "RANDOM_SIMS", 3)
    candles = _synthetic_market(2900, 11)
    shocked = candles.copy()
    test_start = pd.Timestamp(strategy_lab.PERIODS["TESTE"][0])
    late = shocked["timestamp"] >= test_start
    shocked.loc[late, ["open", "high", "low", "close"]] = shocked.loc[late, ["open", "high", "low", "close"]] * 0.2

    def chosen(c: pd.DataFrame) -> pd.DataFrame:
        history = classify_history(c, pd.DataFrame())
        results, grid = strategy_lab.run_lab(
            history, lab.market_from_candles(c), {"PRINCIPAIS": ("BTC/USDT", "ETH/USDT")}
        )
        assert set(results["period"]) == {"TREINO", "VALIDACAO", "TESTE"}
        assert set(grid["period"]) == {"TREINO", "VALIDACAO"}  # a grade nunca mostra teste
        return grid[grid["selected"]][["strategy", "params"]].drop_duplicates().reset_index(drop=True)

    a, b = chosen(candles), chosen(shocked)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == len(lab.GRIDS)
