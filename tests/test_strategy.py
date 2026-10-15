"""Regra SMA 200: fronteira, filtro do BTC, STOP e posições encerradas."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src import pipeline
from src.loaders.positions_store import POSITIONS_SCHEMA
from src.transformers.anomaly_detector import STAGE_BUY, STAGE_NEUTRAL, STAGE_WATCH, classify_history
from src.transformers.trade_simulator import EXIT_REGIME, EXIT_STOP, EXIT_TREND, ExitRules, simulate
from tests.helpers import make_candles, ramp

NO_FNG = pd.DataFrame()


def _last(history: pd.DataFrame, symbol: str) -> pd.Series:
    return history[history["symbol"].eq(symbol)].iloc[-1]


@pytest.mark.parametrize(
    ("last_close", "uptrend"),
    [
        (100.0, False),    # fechamento igual à SMA 200: não é "acima"
        (100.01, True),    # 1 centavo acima
        (99.99, False),    # 1 centavo abaixo
    ],
)
def test_sma200_boundary(last_close: float, uptrend: bool) -> None:
    candles = make_candles({"BTC/USDT": [100.0] * 199 + [last_close]})
    row = _last(classify_history(candles, NO_FNG), "BTC/USDT")
    assert row["uptrend"] == uptrend
    assert row["stage"] == (STAGE_BUY if uptrend else STAGE_NEUTRAL)


def test_sma200_needs_200_days() -> None:
    row = _last(classify_history(make_candles({"BTC/USDT": ramp(50, 150, 199)}), NO_FNG), "BTC/USDT")
    assert pd.isna(row["sma_200"])
    assert not row["uptrend"]


def test_btc_filter_blocks_other_coins() -> None:
    # ETH sobe e está acima da própria SMA 200, mas o BTC cai e fecha abaixo da dele.
    falling = make_candles({"BTC/USDT": ramp(200, 100, 250), "ETH/USDT": ramp(50, 150, 250)})
    eth = _last(classify_history(falling, NO_FNG), "ETH/USDT")
    assert eth["close"] > eth["sma_200"]
    assert not eth["regime_up"]
    assert not eth["uptrend"]
    assert eth["stage"] == STAGE_NEUTRAL

    rising = make_candles({"BTC/USDT": ramp(100, 200, 250), "ETH/USDT": ramp(50, 150, 250)})
    eth = _last(classify_history(rising, NO_FNG), "ETH/USDT")
    assert eth["regime_up"]
    assert eth["uptrend"]
    assert eth["stage"] == STAGE_BUY


def test_watch_stage_near_sma200_and_rising() -> None:
    # 2% abaixo da SMA 200 e subindo há 5 dias; BTC (o próprio filtro) fica em PREPARAR.
    closes = [100.0] * 190 + [96.0, 96.5, 97.0, 97.5, 98.0, 98.5, 98.8, 99.0, 99.0, 99.0]
    row = _last(classify_history(make_candles({"BTC/USDT": closes}), NO_FNG), "BTC/USDT")
    assert -0.03 < row["close"] / row["sma_200"] - 1 < 0
    assert row["stage"] == STAGE_WATCH


def _path(closes: list[float], sma: float = 50.0, regime: bool = True) -> pd.DataFrame:
    days = pd.date_range("2026-01-01", periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame(
        {"symbol": "BTC/USDT", "timestamp": days, "close": closes, "sma_200": sma, "regime_up": regime}
    ).astype({"symbol": "string"})


def _entry(price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_id": ["t"],
            "symbol": pd.Series(["BTC/USDT"], dtype="string"),
            "entry_ts": [pd.Timestamp("2026-01-01", tz="UTC")],
            "entry_price": [price],
        }
    )


def test_stop_triggers_at_minus_20_percent() -> None:
    trade = simulate(_entry(), _path([100, 95, 90, 80.0, 70]), ExitRules(stop_loss=-0.20)).iloc[0]
    assert trade["exit_reason"] == EXIT_STOP
    assert trade["status"] == "FECHADA"
    assert trade["exit_price"] == 80.0


def test_stop_triggers_on_exactly_minus_20_percent_despite_float_error() -> None:
    assert 0.4 / 0.5 - 1.0 > -0.20  # em ponto flutuante a perda de exatamente 20% fica um pouco acima de -0,20
    trade = simulate(_entry(0.5), _path([0.5, 0.4], sma=0.1), ExitRules(stop_loss=-0.20)).iloc[0]
    assert trade["exit_reason"] == EXIT_STOP


def test_stop_boundary_and_disabled() -> None:
    just_above = simulate(_entry(), _path([100, 80.01]), ExitRules(stop_loss=-0.20)).iloc[0]
    assert just_above["status"] == "ABERTA"
    off = simulate(_entry(), _path([100, 60.0]), ExitRules(stop_loss=None)).iloc[0]
    assert off["status"] == "ABERTA"


def test_exit_on_trend_boundary() -> None:
    equal = simulate(_entry(), _path([100, 50.0]), ExitRules(stop_loss=None)).iloc[0]
    assert equal["status"] == "ABERTA"  # fechamento igual à SMA 200 não é "abaixo"
    below = simulate(_entry(), _path([100, 49.99]), ExitRules(stop_loss=None)).iloc[0]
    assert below["exit_reason"] == EXIT_TREND


def test_exit_when_btc_regime_turns_down() -> None:
    hist = _path([100, 101, 102])
    hist["regime_up"] = [True, True, False]
    assert simulate(_entry(), hist, ExitRules(stop_loss=None)).iloc[0]["exit_reason"] == EXIT_REGIME


def test_closed_positions_are_not_advised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history = classify_history(make_candles({"BTC/USDT": ramp(100, 200, 250)}), NO_FNG)
    day = pd.Timestamp("2026-01-10", tz="UTC")
    rows = pd.DataFrame(
        {
            "position_id": ["aberta", "fechada"],
            "symbol": ["BTC/USDT", "BTC/USDT"],
            "entry_ts": [day, day],
            "entry_price": [150.0, 150.0],
            "qty": [1.0, 2.0],
            "closed": [False, True],
            "exit_ts": [pd.NaT, day + pd.Timedelta(days=5)],
            "exit_price": [None, 165.0],
        }
    ).astype(POSITIONS_SCHEMA)
    monkeypatch.setattr(pipeline, "read_positions", lambda: rows)
    monkeypatch.setattr(pipeline, "PUBLIC_DIR", tmp_path)
    available = pd.DataFrame({"symbol": ["BTC/USDT"], "available": [True], "reason": [pd.NA], "last_ts": [pd.NaT]})

    positions = pipeline._publish_positions(history, available)

    assert positions["position_id"].tolist() == ["aberta"]
    assert pd.read_parquet(tmp_path / "positions.parquet")["position_id"].tolist() == ["aberta"]
    closed = pd.read_parquet(tmp_path / "closed_positions.parquet")
    assert closed["position_id"].tolist() == ["fechada"]
    assert closed["return_pct"].iloc[0] == pytest.approx(10.0)
    assert closed["pnl_usd"].iloc[0] == pytest.approx(30.0)
