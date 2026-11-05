"""Esteira de estratégias de tendência: indicadores corretos e sem olhar o futuro."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research"))
import strategy_tester as st  # noqa: E402


def _df(n: int = 1500, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    idx = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC")
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "high": np.maximum(op, close) * 1.003, "low": np.minimum(op, close) * 0.997, "close": close}, index=idx)


def test_wma_matches_direct_definition() -> None:
    x = pd.Series(np.arange(1.0, 31.0) ** 1.3)
    n = 7
    w = np.arange(1, n + 1)
    direct = x.rolling(n).apply(lambda v: float(np.dot(v, w) / w.sum()), raw=True)
    assert st.wma(x, n).to_numpy()[n - 1:] == pytest.approx(direct.to_numpy()[n - 1:], rel=1e-9)


@pytest.mark.parametrize("fam", st.FAMILIES, ids=lambda f: f.name)
def test_signal_is_causal(fam: st.Family) -> None:
    df = _df()
    p = fam.grid[0]
    full = fam.signal(df, p)
    cut = fam.signal(df.iloc[:1000], p)
    assert (full.iloc[:1000].to_numpy() == cut.to_numpy()).all()       # truncar o futuro não muda o passado


def test_execution_next_open_and_cost() -> None:
    df = _df(50)
    pos = pd.Series(0.0, index=df.index)
    pos.iloc[10:20] = 1.0                       # comprado ao fechar o candle 10 .. 19; vende ao fechar o 20
    r = st.strategy_returns(df, pos)
    oo = df["open"].shift(-1) / df["open"] - 1
    assert r.iloc[:11].abs().sum() == 0         # nada antes da execução
    assert r.iloc[11] == pytest.approx(oo.iloc[11] - st.COST)        # compra na abertura do candle 11 (não no fechamento do 10)
    assert r.iloc[12] == pytest.approx(oo.iloc[12])
    assert r.iloc[20] == pytest.approx(oo.iloc[20])                  # ainda comprado no candle 20
    assert r.iloc[21] == pytest.approx(-st.COST)                     # vende na abertura do 21 (decidido no fechamento do 20)


def test_hma_has_values_and_follows_trend() -> None:
    df = _df(3000)
    h = st.hma(df["close"], 100)
    assert h.notna().sum() > 2800 and abs(float(h.iloc[-1] / df["close"].iloc[-1]) - 1) < 0.1


def test_daily_adx_is_causal() -> None:
    df = _df(2000)
    full = st.daily_adx(df)
    cut = st.daily_adx(df.iloc[:1200])
    common = cut.dropna().index
    assert (full.loc[common].iloc[:-24].to_numpy() == cut.loc[common].iloc[:-24].to_numpy()).all()
