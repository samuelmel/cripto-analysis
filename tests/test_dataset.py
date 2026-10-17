"""Fingerprint, trilha de revisões, idempotência e atomicidade da base; histórico de fontes; validação de candles."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.loaders import parquet_loader
from src.loaders.market_store import read_ohlcv, read_revisions, write_ohlcv
from src.loaders.source_log import read_source_history, read_source_log, write_source_log
from src.transformers.data_quality import (
    ISSUE_MISALIGNED,
    ISSUE_NEGATIVE_VOLUME,
    ISSUE_OHLC,
    ISSUE_UNCLOSED,
    audit_candles,
)
from src.transformers.dataset import candle_fingerprint, candle_revisions, dataset_manifest
from tests.helpers import make_candles, ramp

NOW = pd.Timestamp("2026-07-01 00:10", tz="UTC")


def _candles() -> pd.DataFrame:
    return make_candles({"BTC/USDT": ramp(100, 200, 50), "ETH/USDT": ramp(10, 20, 50)})


def test_fingerprint_ignores_row_order_and_detects_value_changes() -> None:
    c = _candles()
    shuffled = c.sample(frac=1.0, random_state=3)
    assert candle_fingerprint(c) == candle_fingerprint(shuffled)
    changed = c.copy()
    changed.loc[10, "close"] += 1e-6
    assert candle_fingerprint(changed) != candle_fingerprint(c)
    assert candle_fingerprint(c.iloc[:-1]) != candle_fingerprint(c)


def test_dataset_manifest_has_one_row_per_symbol() -> None:
    m = dataset_manifest(_candles())
    assert m["symbol"].tolist() == ["BTC/USDT", "ETH/USDT"]
    assert m["rows"].tolist() == [50, 50]
    assert m["sha256"].str.len().eq(64).all()


def test_candle_revisions_only_report_real_changes() -> None:
    old = _candles()
    assert candle_revisions(old, old.copy(), NOW).empty
    assert candle_revisions(None, old, NOW).empty
    new = old.copy()
    new.loc[5, "close"] = 999.0
    rev = candle_revisions(old, new, NOW)
    assert len(rev) == 1
    r = rev.iloc[0]
    assert (r["symbol"], r["column"], r["old_value"], r["new_value"]) == (old.loc[5, "symbol"], "close", old.loc[5, "close"], 999.0)
    assert r["ingested_at"] == NOW


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path / "market"


def test_second_write_is_idempotent(base: Path) -> None:
    c = _candles()
    write_ohlcv(c, base, ingested_at=NOW)
    first = read_ohlcv(["BTC/USDT", "ETH/USDT"], base)
    write_ohlcv(c, base, ingested_at=NOW + pd.Timedelta(days=1))
    second = read_ohlcv(["BTC/USDT", "ETH/USDT"], base)
    pd.testing.assert_frame_equal(first, second)
    assert not second.duplicated(["symbol", "timestamp"]).any()
    assert read_revisions(base).empty


def test_revised_candle_is_kept_in_the_audit_trail(base: Path) -> None:
    c = _candles()
    write_ohlcv(c, base, ingested_at=NOW)
    fixed = c[c["symbol"].eq("BTC/USDT")].copy()
    fixed.loc[fixed.index[0], "close"] = 1.0
    write_ohlcv(fixed, base, ingested_at=NOW + pd.Timedelta(days=1))
    rev = read_revisions(base)
    assert len(rev) == 1 and rev["new_value"].iloc[0] == 1.0
    assert read_ohlcv(["BTC/USDT"], base)["close"].iloc[0] == 1.0  # a base fica com a versão nova


def test_failed_write_leaves_the_previous_file_intact(base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = _candles()
    write_ohlcv(c, base)
    before = read_ohlcv(["BTC/USDT", "ETH/USDT"], base)

    def boom(self: pd.DataFrame, *args: object, **kwargs: object) -> None:
        raise OSError("disco cheio")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(OSError):
        write_ohlcv(make_candles({"BTC/USDT": ramp(1, 2, 60)}), base)
    monkeypatch.undo()
    pd.testing.assert_frame_equal(before, read_ohlcv(["BTC/USDT", "ETH/USDT"], base))
    assert not list(base.rglob("*.tmp"))
    assert parquet_loader.write_parquet is not None


def _event(scope: str, status: str, when: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame([{"source": "binance", "scope": scope, "updated_at": when, "status": status, "rows": 0,
                          "last_data_ts": pd.NaT, "detail": "HTTP 503" if status == "erro" else ""}])


def test_source_log_keeps_the_latest_and_an_append_only_history(tmp_path: Path) -> None:
    write_source_log(_event("BTC/USDT", "erro", NOW), tmp_path)
    write_source_log(_event("BTC/USDT", "ok", NOW + pd.Timedelta(days=1)), tmp_path)
    assert read_source_log(tmp_path)["status"].tolist() == ["ok"]
    assert read_source_history(tmp_path)["status"].tolist() == ["erro", "ok"]


def test_source_log_accepts_a_run_where_every_source_failed(tmp_path: Path) -> None:
    """Regressão: com todas as fontes em erro, last_data_ts só tem NaT (sem fuso) e a gravação quebrava."""
    events = pd.concat([_event("BTC/USDT", "erro", NOW), _event("ETH/USDT", "erro", NOW)], ignore_index=True)
    assert events["last_data_ts"].dtype.kind == "M" and getattr(events["last_data_ts"].dtype, "tz", None) is None
    write_source_log(events, tmp_path)
    assert read_source_log(tmp_path)["status"].tolist() == ["erro", "erro"]


def test_audit_flags_ohlc_volume_alignment_and_unclosed_candles() -> None:
    c = make_candles({"BTC/USDT": ramp(100, 110, 5)}, "2026-06-30")
    c.loc[0, "high"] = 50.0                       # máxima abaixo do fechamento
    c.loc[1, "quote_volume"] = -1.0
    c.loc[2, "timestamp"] = c.loc[2, "timestamp"] + pd.Timedelta(hours=3)
    issues = audit_candles(c, as_of=pd.Timestamp("2026-06-30 12:00", tz="UTC")).set_index("kind")
    assert issues.loc[ISSUE_OHLC, "count"] == 1
    assert issues.loc[ISSUE_NEGATIVE_VOLUME, "count"] == 1
    assert issues.loc[ISSUE_MISALIGNED, "count"] == 1
    assert issues.loc[ISSUE_UNCLOSED, "count"] == 1  # o candle de 30/06 só fecha às 00:00 de 01/07
    clean = make_candles({"BTC/USDT": ramp(100, 110, 5)}, "2026-06-30")
    assert audit_candles(clean, as_of=NOW).empty
