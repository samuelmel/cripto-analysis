"""Pipeline de ponta a ponta numa pasta temporária: --offline, fontes fora do ar, dado velho e fontes misturadas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src import pipeline
from src.config import UNIVERSE
from src.extractors import ExtractorError
from src.loaders.market_store import MixedSourceError, read_ohlcv, write_ohlcv
from src.loaders.sim_wallet_store import read_decisions
from src.loaders.source_log import read_source_log
from src.transformers.anomaly_detector import STAGE_BUY, STAGE_UNAVAILABLE
from src.transformers.entry_study import LEVEL_SCHEMA
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


def _publish_levels(workdir: Path, levels: dict[str, str]) -> None:
    rows = [{"combo": c, "candidate": c[0], "kind": "SELECAO", "level": lv, "n_signals_7": 100, "n_signals_30": 100}
            for c, lv in levels.items()]
    frame = pd.DataFrame(rows).reindex(columns=list(LEVEL_SCHEMA)).astype(LEVEL_SCHEMA)
    write_parquet(frame, workdir / "evidence" / "entry_signals" / "entry_signal_levels.parquet")


def test_buy_stage_requires_a_validated_entry_signal(workdir: Path) -> None:
    """COMPRAR depende do sinal, não da moeda (docs/entry_signals.md): validação por moeda não libera mais COMPRAR."""
    write_ohlcv(_base())
    none = pipeline.analyze(pd.Timestamp.now(tz="UTC"))
    assert not none["signals"]["stage"].eq(STAGE_BUY).any()  # sem a tabela de níveis, falha fechada
    assert none["recommendation"]["data_status"].iloc[0] == "OK"  # a falta da evidência não é falha de dados
    _publish_evidence(workdir, ("BTC/USDT", "SOL/USDT"))
    per_coin = pipeline.analyze(pd.Timestamp.now(tz="UTC"))["signals"]
    assert not per_coin["stage"].eq(STAGE_BUY).any()  # moeda validada individualmente: só informação
    _publish_levels(workdir, {"A_30": "PROMISSOR"})
    watch = pipeline.analyze(pd.Timestamp.now(tz="UTC"))["signals"]
    assert not watch["stage"].eq(STAGE_BUY).any()  # PROMISSOR nunca vira COMPRAR
    assert watch["entry_level"].eq("PROMISSOR").sum() == 5  # top 5 de 30 dias em observação
    _publish_levels(workdir, {"A_30": "VALIDADO"})
    buy = pipeline.analyze(pd.Timestamp.now(tz="UTC"))["signals"]
    assert buy["stage"].eq(STAGE_BUY).sum() == 5
    assert buy.loc[buy["stage"].eq(STAGE_BUY), "entry_level"].eq("VALIDADO").all()


def test_offline_pipeline_runs_and_publishes(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_ohlcv(_base())
    _publish_levels(workdir, {"A_30": "VALIDADO"})

    assert pipeline.main(["--offline"]) == 0

    out = capsys.readouterr().out
    assert "estágios" in out
    for name in PUBLISHED:
        assert (workdir / "frontend" / "public" / f"{name}.parquet").is_file(), name
    assert (workdir / "frontend" / "public" / "entry_signal_levels.parquet").is_file()
    signals = pd.read_parquet(workdir / "frontend" / "public" / "daily_signals.parquet")
    assert len(signals) == len(UNIVERSE)
    assert signals["stage"].eq(STAGE_BUY).sum() == 5
    assert signals["stage_reason"].isna().all()


def test_each_run_records_the_fingerprint_of_the_data_it_used(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from src.loaders.market_store import read_dataset_manifests

    write_ohlcv(_base())
    assert pipeline.main(["--offline"]) == 0
    assert pipeline.main(["--offline"]) == 0
    runs = read_dataset_manifests()
    assert runs["run_ts"].nunique() == 2
    assert runs.groupby("symbol")["sha256"].nunique().eq(1).all()  # mesmos dados = mesmo hash
    assert "SHA-256" in capsys.readouterr().out


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


def test_usdt_brl_rate_is_downloaded_outside_the_universe_and_its_failure_is_not_a_source_error(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "BinanceAdapter", FakeBinance)
    monkeypatch.setattr(pipeline, "FearGreedAdapter", FakeFng)
    monkeypatch.setattr(pipeline, "CoinGeckoMarketAdapter", FakeCoinGecko)
    FakeBinance.fail = {"ETH/USDT"}

    log = pipeline.update_base(datetime.now(tz=_yesterday().tz))

    assert read_ohlcv(["USDT/BRL"])["symbol"].eq("USDT/BRL").all()
    assert "USDT/BRL" not in set(read_ohlcv(list(UNIVERSE))["symbol"]) and "USDT/BRL" not in set(log["scope"])
    FakeBinance.fail = {"ETH/USDT", "USDT/BRL"}
    try:
        assert pipeline.update_quote_rate(datetime.now(tz=_yesterday().tz), rebuild=True) is not None  # falha: devolve o erro
    finally:
        FakeBinance.fail = {"ETH/USDT"}
    assert len(log) == len(UNIVERSE) + 2  # a cotação não entra no registro de fontes


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


def _usdt_brl() -> pd.DataFrame:
    return make_candles({"USDT/BRL": [5.0] * 60}, _yesterday())


def test_simulated_wallets_are_published_recorded_once_and_shown_without_changing_the_recommendation(
    workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_ohlcv(_base())
    write_ohlcv(_usdt_brl())
    now = pd.Timestamp.now(tz="UTC")

    result = pipeline.analyze(now, record_state=True)
    assert result["sim_summary"]["wallet"].tolist() == ["PAINEL", "IA", "REVERSAO", "SO_BTC"]
    assert result["sim_summary"]["currency"].eq("BRL").all() and result["sim_notes"].empty
    stored = read_decisions()
    assert stored["wallet"].eq("SO_BTC").any() and stored["side"].eq("COMPRA").all()  # nada vende no primeiro dia
    assert (workdir / "frontend" / "public" / "sim_wallets.parquet").is_file()
    assert (workdir / "frontend" / "public" / "sim_wallet_positions.parquet").is_file()

    assert pipeline._notify(result, now.to_pydatetime(), dry_run=True, detailed=True) == 0
    out = capsys.readouterr().out
    assert "CARTEIRAS SIMULADAS (dinheiro fictício, sem ordens reais)" in out and "nenhuma ordem real é enviada" in out
    assert out.index("CARTEIRAS SIMULADAS") > out.index("--- mensagem 1/")  # numa mensagem separada, depois do resumo

    pipeline.analyze(now, record_state=True)
    assert len(read_decisions()) == len(stored)  # mesmo dia: idempotente

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("falha de teste")

    monkeypatch.setattr(pipeline, "replay", boom)
    failed = pipeline.analyze(now)
    assert failed["sim_summary"].empty and failed["sim_notes"]["note"].str.contains("falharam").all()
    pd.testing.assert_frame_equal(failed["recommendation"], result["recommendation"])  # a simulação não mexe na recomendação
    pd.testing.assert_frame_equal(failed["signals"], result["signals"])


def test_simulated_wallets_without_the_real_quote_say_so_and_never_invent_one(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_ohlcv(_base())  # sem USDT/BRL na base
    now = pd.Timestamp.now(tz="UTC")
    result = pipeline.analyze(now)
    assert result["sim_summary"]["currency"].eq("USDT").all() and result["sim_summary"]["fx_close"].isna().all()
    assert result["sim_trades"]["status"].isin(["PENDENTE", "NAO_EXECUTADA"]).all()
    assert pipeline._notify(result, now.to_pydatetime(), dry_run=True, detailed=True) == 0
    assert "cotação do real indisponível" in capsys.readouterr().out
