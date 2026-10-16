"""Loaders (I/O de borda): escrita atômica, compressão, snapshots diários e upsert idempotente da base; e a
consistência entre as duas definições do filtro de regime do BTC. Sem rede."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from src.loaders.history_store import read_previous, snapshot_path, write_snapshot
from src.loaders.market_store import last_timestamp, read_ohlcv, write_ohlcv
from src.loaders.parquet_loader import write_daily_signals, write_parquet
from src.transformers.anomaly_detector import classify_history
from src.transformers.selection import (
    REGIME_DEFENSIVE,
    REGIME_FAVORABLE,
    REGIME_NEUTRAL,
    compute_features,
    regime_series,
)
from src.transformers.strategies import market_from_candles
from tests.helpers import make_candles, ramp


def test_write_parquet_is_atomic_a_failed_write_keeps_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out" / "x.parquet"
    write_parquet(pd.DataFrame({"a": [1, 2, 3]}), target)

    def boom(self: pd.DataFrame, *args: object, **kwargs: object) -> None:
        raise OSError("disco cheio")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(OSError):
        write_parquet(pd.DataFrame({"a": [9, 9]}), target)
    monkeypatch.undo()
    assert pd.read_parquet(target)["a"].tolist() == [1, 2, 3]  # o arquivo anterior permanece intacto
    assert [p.name for p in target.parent.iterdir()] == ["x.parquet"]  # e nenhum temporário ficou para trás


def test_daily_signals_are_snappy_compressed(tmp_path: Path) -> None:
    path = write_daily_signals(pd.DataFrame({"a": [1.0, 2.0]}), tmp_path / "daily_signals.parquet")
    assert pq.ParquetFile(path).metadata.row_group(0).column(0).compression == "SNAPPY"  # CLAUDE.md §3


def test_history_snapshots_return_the_last_day_strictly_before(tmp_path: Path) -> None:
    base = tmp_path / "history"
    assert read_previous(pd.Timestamp("2026-06-30"), base) is None
    for day, value in (("2026-06-27", 1), ("2026-06-28", 2), ("2026-06-30", 3)):
        write_snapshot(pd.DataFrame({"v": [value]}), pd.Timestamp(day), base)
    assert read_previous(pd.Timestamp("2026-06-30"), base)["v"].iloc[0] == 2  # type: ignore[index]
    assert read_previous(pd.Timestamp("2026-06-27"), base) is None
    write_snapshot(pd.DataFrame({"v": [99]}), pd.Timestamp("2026-06-28"), base)  # reexecutar no mesmo dia sobrescreve
    assert pd.read_parquet(snapshot_path(pd.Timestamp("2026-06-28"), base))["v"].tolist() == [99]


def test_market_store_upsert_is_idempotent_resumable_and_keeps_the_latest_version(tmp_path: Path) -> None:
    candles = make_candles({"BTC/USDT": ramp(100, 130, 31)}, "2026-06-30")
    write_ohlcv(candles, tmp_path)
    write_ohlcv(candles, tmp_path)  # repetir a mesma carga não duplica nada
    stored = read_ohlcv(["BTC/USDT"], tmp_path)
    assert len(stored) == 31 and stored["timestamp"].is_unique and stored["timestamp"].is_monotonic_increasing
    assert last_timestamp("BTC/USDT", tmp_path) == pd.Timestamp("2026-06-30", tz="UTC")
    assert last_timestamp("ETH/USDT", tmp_path) is None
    revised = candles.tail(2).assign(close=[500.0, 501.0])  # o fornecedor corrigiu os dois últimos dias
    more = make_candles({"BTC/USDT": ramp(130, 140, 5)}, "2026-07-05")
    write_ohlcv(pd.concat([revised, more.tail(5)], ignore_index=True), tmp_path)  # retomada: sobrepõe e estende
    stored = read_ohlcv(["BTC/USDT"], tmp_path)
    assert stored["timestamp"].is_unique and len(stored) == 36
    assert stored.set_index("timestamp").loc[pd.Timestamp("2026-06-30", tz="UTC"), "close"] == 501.0
    assert read_ohlcv(["SOL/USDT"], tmp_path).empty  # moeda sem base: ignorada, sem erro


def test_the_two_btc_regime_definitions_agree_on_every_classifiable_day() -> None:
    """`anomaly_detector.regime_up` (estágio SMA 200) e `selection.regime_series` (seleção) calculam a mesma ideia em
    dois lugares: BTC acima da SMA 200. Se divergirem, o painel e a seleção contam histórias diferentes."""
    rng = np.random.default_rng(11)
    drift = np.where(np.arange(700) // 175 % 2 == 0, 0.004, -0.005)
    close = 100.0 * np.exp(np.cumsum(drift + 0.012 * rng.standard_normal(700)))
    candles = make_candles({"BTC/USDT": list(close)}, "2026-06-30")
    history = classify_history(candles, pd.DataFrame())
    up = history[history["symbol"].eq("BTC/USDT")].set_index("timestamp")["regime_up"]
    regime = regime_series(compute_features(market_from_candles(candles)))
    both = up[up.index.isin(regime.index)]
    classifiable = regime.reindex(both.index).isin([REGIME_FAVORABLE, REGIME_NEUTRAL, REGIME_DEFENSIVE])
    assert classifiable.sum() > 400  # o teste cobre ciclos de alta e de queda
    expected = regime.reindex(both.index).isin([REGIME_FAVORABLE, REGIME_NEUTRAL])
    assert (both[classifiable] == expected[classifiable]).all()
    assert both[classifiable].any() and not both[classifiable].all()
