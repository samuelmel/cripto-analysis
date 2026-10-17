"""Pipeline de ponta a ponta numa pasta temporária: --offline, fontes fora do ar, dado velho e fontes misturadas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src import pipeline
from src.config import RECOMMENDED, UNIVERSE
from src.extractors import ExtractorError
from src.loaders.market_store import MixedSourceError, read_ohlcv, write_ohlcv
from src.loaders.source_log import read_source_log
from src.transformers.anomaly_detector import STAGE_BUY, STAGE_UNAVAILABLE
from src.loaders.parquet_loader import write_parquet
from src.transformers.recommendation import validate_recommendation
from src.transformers.signal_validation import EVIDENCE_SCHEMA
from tests.helpers import make_candles, ramp

PUBLISHED = ("daily_signals", "history", "backtest", "performance", "forecast", "sources", "positions", "closed_positions")


def _yesterday() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").floor("D") - pd.Timedelta(days=1)


def _base() -> pd.DataFrame:
    series = {s: ramp(50, 150, 420) for s in UNIVERSE}
    return make_candles(series, _yesterday())


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _publish_evidence(workdir: Path, validated: tuple[str, ...]) -> None:
    rows = [{"symbol": s, "status": "VALIDADA" if s in validated else "NAO_VALIDADA", "holdout": "NAO_APLICA", "reason": "teste"}
            for s in UNIVERSE]
    frame = pd.DataFrame(rows).reindex(columns=list(EVIDENCE_SCHEMA)).astype(EVIDENCE_SCHEMA)
    write_parquet(frame, workdir / "evidence" / "signal_evidence.parquet")


def test_buy_stage_requires_statistical_evidence(workdir: Path) -> None:
    write_ohlcv(_base())
    none = pipeline.analyze(pd.Timestamp.now(tz="UTC"))
    assert not none["signals"]["stage"].eq(STAGE_BUY).any()  # sem a tabela de evidência, falha fechada
    assert any("não foi publicada" in str(n) for n in none["recommendation"]["data_notes"].iloc[0])
    _publish_evidence(workdir, ("BTC/USDT", "SOL/USDT"))
    some = pipeline.analyze(pd.Timestamp.now(tz="UTC"))["signals"].set_index("symbol")
    assert some.loc["BTC/USDT", "stage"] == STAGE_BUY and some.loc["SOL/USDT", "stage"] == STAGE_BUY  # vale para qualquer moeda validada
    assert some.loc["ETH/USDT", "stage"] != STAGE_BUY  # não validada: só ranking
    assert some["stage"].eq(STAGE_BUY).sum() == 2


def test_offline_pipeline_runs_and_publishes(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_ohlcv(_base())
    _publish_evidence(workdir, tuple(RECOMMENDED))

    assert pipeline.main(["--offline"]) == 0

    out = capsys.readouterr().out
    assert "estágios" in out
    for name in PUBLISHED:
        assert (workdir / "frontend" / "public" / f"{name}.parquet").is_file(), name
    signals = pd.read_parquet(workdir / "frontend" / "public" / "daily_signals.parquet")
    assert len(signals) == len(UNIVERSE)
    assert signals.set_index("symbol").loc[list(RECOMMENDED), "stage"].eq(STAGE_BUY).all()
    assert signals["stage_reason"].isna().all()


def test_offline_pipeline_with_stale_base_marks_everything_unavailable(workdir: Path) -> None:
    write_ohlcv(_base())
    result = pipeline.analyze(pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=10))
    signals = result["signals"]
    assert signals["stage"].eq(STAGE_UNAVAILABLE).all()
    assert signals["alert"].isna().all()
    assert signals["stage_reason"].str.contains("desatualizado").all()
    assert result["availability"]["available"].sum() == 0


def test_offline_pipeline_fails_cleanly_without_a_base(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert pipeline.main(["--offline"]) == 1


class FakeBinance:
    source = "binance"
    fail: set[str] = {"ETH/USDT"}

    hosts: list[str] = []

    def __init__(self, symbols: list[str], *, host: str = "") -> None:
        self.symbols = symbols
        FakeBinance.hosts.append(host)

    def extract(self, start: datetime | None, end: datetime) -> pd.DataFrame:
        if self.symbols[0] in self.fail:
            raise ExtractorError("GET https://api.binance.com/api/v3/klines falhou: HTTP 503")
        return make_candles({self.symbols[0]: ramp(50, 150, 30)}, _yesterday())


class FakeSecondary:
    def __init__(self, *args: Any) -> None:
        pass

    def extract(self, start: datetime | None, end: datetime) -> pd.DataFrame:
        raise ExtractorError("resposta incompleta, faltam campos ['market_cap']")

    def standardize(self, df: pd.DataFrame) -> pd.DataFrame:
        return df


class FakeFng(FakeSecondary):
    source = "alternative_me"


class FakeCoinGecko(FakeSecondary):
    source = "coingecko"


def test_update_base_survives_source_failures_and_logs_them(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "BinanceAdapter", FakeBinance)
    monkeypatch.setattr(pipeline, "FearGreedAdapter", FakeFng)
    monkeypatch.setattr(pipeline, "CoinGeckoMarketAdapter", FakeCoinGecko)

    log = pipeline.update_base(datetime.now(tz=_yesterday().tz))

    assert len(log) == len(UNIVERSE) + 2
    failed = log[log["status"].eq("erro")]
    assert set(failed["scope"]) == {"ETH/USDT", "MARKET"}
    assert set(failed["source"]) == {"binance", "alternative_me", "coingecko"}
    assert log[log["scope"].eq("BTC/USDT")]["status"].iloc[0] == "ok"
    assert "ETH/USDT" not in set(read_ohlcv(list(UNIVERSE))["symbol"])  # a base não ganhou dado velho nem inventado

    stored = read_source_log()
    assert len(stored) == len(log)
    assert stored["updated_at"].notna().all()
    assert stored.loc[stored["scope"].eq("BTC/USDT"), "last_data_ts"].iloc[0] == _yesterday()


def test_secondary_sources_down_do_not_stop_the_analysis(workdir: Path) -> None:
    write_ohlcv(_base())  # sem Fear & Greed nem CoinGecko na base
    result = pipeline.analyze(pd.Timestamp.now(tz="UTC"))
    assert result["signals"]["market_cap_usd"].isna().all()
    assert result["signals"]["fng_value"].isna().all()
    assert not result["signals"]["panic"].any()


def test_candles_from_another_source_are_not_mixed(workdir: Path) -> None:
    write_ohlcv(make_candles({"BTC/USDT": ramp(10, 20, 50)}, _yesterday()))
    with pytest.raises(MixedSourceError, match="não misturamos"):
        write_ohlcv(make_candles({"BTC/USDT": ramp(10, 20, 50)}, _yesterday(), source="outra"))
    assert read_ohlcv(["BTC/USDT"])["source"].unique().tolist() == ["binance"]


def test_update_base_passes_the_binance_host_to_the_adapter(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBinance.hosts = []
    monkeypatch.setattr(pipeline, "BinanceAdapter", FakeBinance)
    monkeypatch.setattr(pipeline, "FearGreedAdapter", FakeFng)
    monkeypatch.setattr(pipeline, "CoinGeckoMarketAdapter", FakeCoinGecko)

    pipeline.update_base(datetime.now(tz=_yesterday().tz), binance_host="https://data-api.binance.vision")

    assert set(FakeBinance.hosts) == {"https://data-api.binance.vision"}


def test_pipeline_publishes_a_consistent_recommendation_within_the_budget(workdir: Path) -> None:
    write_ohlcv(_base())
    assert pipeline.main(["--offline", "--budget", "55"]) == 0
    public = workdir / "frontend" / "public"
    signals = pd.read_parquet(public / "daily_signals.parquet")
    rec = pd.read_parquet(public / "recommendation.parquet")
    perf = pd.read_parquet(public / "selection_backtest.parquet")
    assert len(rec) == 1 and rec["budget_brl"].iloc[0] == 55.0
    assert signals["allocation_brl"].sum() <= 55.0
    assert rec["total_brl"].iloc[0] == signals["allocation_brl"].sum()
    assert signals["run_ts"].eq(rec["run_ts"].iloc[0]).all()
    assert {"opportunity", "score", "reasons", "risks", "blockers"} <= set(signals.columns)
    assert not perf.empty and "SELECAO" in set(perf["strategy"])
    assert validate_recommendation(signals, rec) == []


def test_stale_base_never_recommends_a_buy(workdir: Path) -> None:
    write_ohlcv(_base())
    result = pipeline.analyze(pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=10))
    assert result["signals"]["allocation_brl"].sum() == 0
    assert not result["signals"]["selected"].any()
    assert result["recommendation"]["total_brl"].iloc[0] == 0
    assert result["recommendation"]["data_status"].iloc[0] in ("PARCIAL", "INDISPONIVEL")


def test_negative_budget_is_rejected(workdir: Path) -> None:
    write_ohlcv(_base())
    with pytest.raises(SystemExit):
        pipeline.main(["--offline", "--budget", "-10"])
