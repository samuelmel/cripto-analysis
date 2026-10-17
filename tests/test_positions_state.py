"""Estados das posições (SEGURAR, ATENÇÃO, VENDER), histórico, aviso só na mudança, registro imutável de sinais e a branch `state`."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import pipeline, state_sync
from src.loaders.market_store import write_fng, write_ohlcv
from src.loaders.parquet_loader import write_parquet
from src.loaders.positions_store import POSITIONS_SCHEMA
from src.loaders.position_log_store import read_notifications, read_state_log
from src.loaders.signal_log_store import LogIntegrityError, append_signal_log, read_signal_log
from src.transformers.notification import POSITION_DISCLAIMER, format_position_changes, validate_messages
from src.transformers.position_advisor import ACTION_HOLD, ACTION_SELL, ACTION_UNAVAILABLE, ACTION_WATCH, advise
from src.transformers.position_log import acknowledgements, new_state_rows, pending_changes
from src.transformers.signal_registry import GENESIS, build_rows, chain_rows, config_version, verify_chain
from tests.helpers import make_candles, ramp
from tests.synthetic_market import RUN_TS, synthetic_candles, synthetic_fng

DAY0 = pd.Timestamp("2026-01-01", tz="UTC")


def history(closes: list[float], *, sma: float = 50.0, btc_close: float = 100.0, btc_sma: float = 80.0, symbol: str = "SOL/USDT") -> pd.DataFrame:
    """Histórico mínimo de uma moeda e do BTC (o que `advise` lê)."""
    days = pd.date_range(DAY0, periods=len(closes), freq="D", tz="UTC")
    coin = pd.DataFrame({"symbol": symbol, "timestamp": days, "close": closes, "sma_200": sma, "regime_up": btc_close > btc_sma})
    btc = pd.DataFrame({"symbol": "BTC/USDT", "timestamp": days, "close": btc_close, "sma_200": btc_sma, "regime_up": btc_close > btc_sma})
    return pd.concat([coin, btc], ignore_index=True).astype({"symbol": "string"})


def position(symbol: str = "SOL/USDT", price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {"position_id": ["p1"], "symbol": [symbol], "entry_ts": [DAY0], "entry_price": [price], "qty": [1.0]}
    ).astype({"position_id": "string", "symbol": "string"})


def advised(closes: list[float], **over: float) -> pd.Series:
    trailing = over.pop("trailing", None)
    out = advise(position(), history(closes, **over), trailing=trailing)
    assert len(out) == 1
    return out.iloc[0]


# ---------------------------------------------------------------------------------------------- estado por regra

def test_hold_when_no_rule_is_close() -> None:
    p = advised([100, 105, 110])
    assert p["action"] == ACTION_HOLD and pd.isna(p["state_rule"])


def test_a_20_percent_fall_sells_by_stop_and_the_stop_is_permanent() -> None:
    p = advised([100, 90, 79])
    assert p["action"] == ACTION_SELL and p["state_rule"] == "STOP" and "-20" in str(p["state_detail"]).replace("−", "-")
    rebound = advised([100, 79, 98, 105])
    assert rebound["action"] == ACTION_SELL and rebound["state_rule"] == "STOP"  # voltou, mas o stop já disparou


def test_losing_the_sma_200_sells_by_trend() -> None:
    p = advised([100, 120, 95], sma=100.0)  # -5% sobre a compra (sem stop), mas abaixo da SMA 200
    assert p["action"] == ACTION_SELL and p["state_rule"] == "TENDENCIA"


def test_bitcoin_below_its_sma_sells_by_market() -> None:
    p = advised([100, 110, 120], btc_close=70.0, btc_sma=80.0)
    assert p["action"] == ACTION_SELL and p["state_rule"] == "MERCADO"


def test_attention_halfway_to_a_rule() -> None:
    down = advised([100, 90.0])  # -10%: metade do caminho até o stop
    assert down["action"] == ACTION_WATCH and down["state_rule"] == "STOP"
    near_sma = advised([100, 110, 126], sma=125.0)  # a 0,8% acima da SMA 200
    assert near_sma["action"] == ACTION_WATCH and near_sma["state_rule"] == "TENDENCIA"
    near_btc = advised([100, 110], btc_close=81.0, btc_sma=80.0)
    assert near_btc["action"] == ACTION_WATCH and near_btc["state_rule"] == "MERCADO"


def test_trailing_is_only_a_warning_unless_adopted() -> None:
    path = [100, 150, 135]  # -10% desde o topo
    info = advised(path)
    assert info["action"] == ACTION_WATCH and info["state_rule"] == "TRAILING"
    fired = advised([100, 150, 112], trailing=0.20)  # -25% desde o topo
    assert fired["action"] == ACTION_SELL and fired["state_rule"] == "TRAILING"
    assert advised([100, 150, 112])["action"] != ACTION_SELL  # sem trailing adotado nada dispara


def test_drawdowns_and_current_result_are_reported() -> None:
    p = advised([100, 130, 85, 100])
    assert p["return_pct"] == pytest.approx(0.0)
    assert p["drawdown_entry_pct"] == pytest.approx(-15.0)       # pior ponto sobre o preço pago
    assert p["drawdown_peak_pct"] == pytest.approx((100 / 130 - 1) * 100)


def test_rule_evidence_text_comes_from_the_backtest_table() -> None:
    table = pd.DataFrame({"rule": ["STOP"], "adopted": [True], "n": [61], "mean_return": [-0.25], "share_fell_after": [0.49]})
    out = advise(position(), history([100, 79]), rule_table=table).iloc[0]
    assert "61 disparos" in str(out["rule_evidence"]) and "49%" in str(out["rule_evidence"])


def test_position_in_a_coin_other_than_btc_and_eth_works() -> None:
    for symbol in ("NEAR/USDT", "DOGE/USDT"):
        out = advise(position(symbol), history([100, 79], symbol=symbol)).iloc[0]
        assert out["symbol"] == symbol and out["action"] == ACTION_SELL


def test_without_reliable_data_the_state_is_unavailable() -> None:
    available = pd.DataFrame({"symbol": ["SOL/USDT"], "available": [False], "reason": ["dado velho"], "last_ts": [pd.NaT]})
    out = advise(position(), history([100, 105]), available=available).iloc[0]
    assert out["action"] == ACTION_UNAVAILABLE


# ------------------------------------------------------------------------------- histórico e aviso só na mudança

def row(state: str, rule: str | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {"position_id": ["p1"], "symbol": ["SOL/USDT"], "action": [state], "state_rule": [rule], "state_detail": ["detalhe" if rule else None],
         "return_pct": [-5.0], "drawdown_entry_pct": [-8.0], "drawdown_peak_pct": [-9.0], "last_close": [95.0], "rule_evidence": ["STOP: 61 disparos" if rule else None]}
    )


def test_notice_only_when_the_state_changes() -> None:
    log = new_state_rows(row(ACTION_HOLD), pd.DataFrame(), DAY0)
    assert not log["changed"].any()                                       # nasce em SEGURAR: nada a avisar
    day1 = new_state_rows(row(ACTION_SELL, "STOP"), log, DAY0 + pd.Timedelta(days=1))
    log = pd.concat([log, day1], ignore_index=True)
    assert day1["changed"].tolist() == [True] and day1["prev_state"].tolist() == [ACTION_HOLD]
    day2 = new_state_rows(row(ACTION_SELL, "STOP"), log, DAY0 + pd.Timedelta(days=2))
    assert day2["changed"].tolist() == [False]                            # continua em VENDER: não repete
    day3 = new_state_rows(row(ACTION_HOLD), pd.concat([log, day2], ignore_index=True), DAY0 + pd.Timedelta(days=3))
    assert day3["changed"].tolist() == [True]                             # VENDER -> SEGURAR também é mudança


def test_same_day_rerun_adds_nothing_and_sent_changes_are_not_pending() -> None:
    log = new_state_rows(row(ACTION_SELL, "STOP"), pd.DataFrame(), DAY0)
    assert log["changed"].tolist() == [True]                              # já nasce fora de SEGURAR
    assert new_state_rows(row(ACTION_SELL, "STOP"), log, DAY0).empty
    pending = pending_changes(log, pd.DataFrame())
    assert len(pending) == 1
    acks = acknowledgements(pending, DAY0 + pd.Timedelta(hours=1))
    assert pending_changes(log, acks).empty                               # enviado: não reenvia
    assert len(pending_changes(log, pd.DataFrame())) == 1                 # falha de envio (nada gravado): reenvia


def test_unavailable_data_never_notifies_and_does_not_count_as_a_state() -> None:
    log = new_state_rows(row(ACTION_HOLD), pd.DataFrame(), DAY0)
    out = new_state_rows(row(ACTION_UNAVAILABLE), log, DAY0 + pd.Timedelta(days=1))
    assert out["changed"].tolist() == [False]
    after = new_state_rows(row(ACTION_HOLD), pd.concat([log, out], ignore_index=True), DAY0 + pd.Timedelta(days=2))
    assert after["changed"].tolist() == [False]                           # SEGURAR -> (sem dados) -> SEGURAR não é mudança


def test_telegram_text_names_the_rule_the_history_and_the_disclaimer() -> None:
    log = new_state_rows(row(ACTION_SELL, "STOP"), pd.DataFrame(), DAY0)
    texts = format_position_changes(pending_changes(log, pd.DataFrame()), now=pd.Timestamp("2026-01-02 12:00", tz="UTC"))
    text = "\n".join(texts)
    assert "SOL: nova posição → VENDER" in text and "Regra: STOP" in text and "STOP: 61 disparos" in text
    assert POSITION_DISCLAIMER in text and "Nenhuma ordem é executada" in text
    assert validate_messages(texts) == []
    assert format_position_changes(pending_changes(log, acknowledgements(log, DAY0)), now=DAY0) == []  # sem mudança: sem mensagem


def test_message_never_contains_a_secret() -> None:
    log = new_state_rows(row(ACTION_SELL, "STOP"), pd.DataFrame(), DAY0)
    texts = format_position_changes(pending_changes(log, pd.DataFrame()), now=DAY0)
    assert validate_messages(texts, ["123456:ABC-DEF-segredo", "chat-id-secreto"]) == []


# ------------------------------------------------------------------------------------ registro imutável de sinais

def signals_frame(day: str = "2026-01-10", n: int = 3) -> pd.DataFrame:
    ts = pd.Timestamp(day, tz="UTC")
    return pd.DataFrame(
        {"timestamp": [ts] * n, "symbol": pd.Series([f"C{i}/USDT" for i in range(n)], dtype="string"), "stage": pd.Series(["NEUTRO"] * n, dtype="string"),
         "alert": pd.Series([pd.NA] * n, dtype="string"), "uptrend": [True, False, True][:n], "close": [1.0, 2.0, 3.0][:n],
         "score": [70.0, 50.0, np.nan][:n], "opportunity": pd.Series(["BOA_RELATIVA", "AGUARDAR", "EVITAR"][:n], dtype="string"),
         "selected": [True, False, False][:n], "candidate_rank": pd.Series([1, pd.NA, pd.NA][:n], dtype="Int64")}
    )


def test_signal_log_is_append_only_and_chained(tmp_path: Path) -> None:
    path = tmp_path / "signal_log.parquet"
    ev = pd.DataFrame({"symbol": ["C0/USDT"], "status": ["NAO_VALIDADA"], "excess_7": [0.01], "excess_30": [-0.02], "p_holm_30": [1.0]})
    rows = build_rows(signals_frame(), ev, run_ts=pd.Timestamp("2026-01-11", tz="UTC"), code_version="abc")
    assert append_signal_log(rows, path) == 3
    assert append_signal_log(rows, path) == 0                              # mesmo dia e moeda: o passado não é reescrito
    changed = rows.assign(stage="COMPRAR", score=99.0)
    assert append_signal_log(changed, path) == 0                           # nem com valores diferentes
    later = build_rows(signals_frame("2026-01-11"), ev, run_ts=pd.Timestamp("2026-01-12", tz="UTC"), code_version="abc")
    assert append_signal_log(later, path) == 3
    log = read_signal_log(path)
    assert len(log) == 6 and verify_chain(log) == []
    assert log["prev_hash"].iloc[0] == GENESIS and log["prev_hash"].iloc[3] == log["row_hash"].iloc[2]
    assert set(log["evidence_status"]) == {"NAO_VALIDADA", "NAO_AVALIADA"}
    assert log["config_version"].nunique() == 1 and log["config_version"].iloc[0] == config_version()


def test_tampering_with_the_past_is_detected_and_blocks_the_append(tmp_path: Path) -> None:
    path = tmp_path / "signal_log.parquet"
    rows = build_rows(signals_frame(), pd.DataFrame(), run_ts=pd.Timestamp("2026-01-11", tz="UTC"), code_version="abc")
    append_signal_log(rows, path)
    log = read_signal_log(path)
    forged = log.copy()
    forged.loc[0, "stage"] = "COMPRAR"                                     # reescrever o passado
    assert any("alterada" in p for p in verify_chain(forged))
    write_parquet(forged, path)
    with pytest.raises(LogIntegrityError):
        append_signal_log(build_rows(signals_frame("2026-01-12"), pd.DataFrame(), run_ts=pd.Timestamp("2026-01-13", tz="UTC"), code_version="abc"), path)
    assert len(read_signal_log(path)) == 3                                 # nada foi gravado depois da adulteração
    dropped = log.iloc[[0, 2]].reset_index(drop=True)                      # apagar uma linha do meio
    assert any("elo quebrado" in p for p in verify_chain(dropped))


def test_chain_rows_skips_existing_pairs_and_sorts() -> None:
    first = chain_rows(pd.DataFrame(), build_rows(signals_frame(), pd.DataFrame(), run_ts=DAY0, code_version="x"))
    again = chain_rows(first, build_rows(signals_frame(), pd.DataFrame(), run_ts=DAY0, code_version="x"))
    assert again.empty and verify_chain(first) == []


# ---------------------------------------------------------------------------------- pipeline de ponta a ponta

@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def seed_market(symbol_drop: str | None = None) -> None:
    candles = synthetic_candles()
    write_ohlcv(candles)
    write_fng(synthetic_fng(candles))


def write_position(workdir: Path, symbol: str, price: float) -> None:
    frame = pd.DataFrame(
        {"position_id": ["p1"], "symbol": [symbol], "entry_ts": [RUN_TS.floor("D") - pd.Timedelta(days=30)], "entry_price": [price],
         "qty": [1.0], "closed": [False], "exit_ts": pd.Series([pd.NaT], dtype="datetime64[ns, UTC]"),
         "exit_price": pd.Series([np.nan], dtype="float64")}
    ).astype(POSITIONS_SCHEMA)
    write_parquet(frame, workdir / "data" / "state" / "positions.parquet")


def test_pipeline_records_state_only_when_asked(workdir: Path) -> None:
    seed_market()
    pipeline.analyze(RUN_TS)
    assert not (workdir / "data" / "state" / "signal_log.parquet").exists()      # sem --record-state nada é gravado
    result = pipeline.analyze(RUN_TS, record_state=True)
    log = read_signal_log(workdir / "data" / "state" / "signal_log.parquet")
    assert len(log) == len(result["signals"]) and verify_chain(log) == []
    again = pipeline.analyze(RUN_TS, record_state=True)
    assert len(read_signal_log(workdir / "data" / "state" / "signal_log.parquet")) == len(log)  # idempotente no dia
    assert len(again["signals"]) == len(result["signals"])


def test_position_in_any_coin_is_tracked_and_notified_once(workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seed_market()
    base = pipeline.analyze(RUN_TS)["signals"].set_index("symbol")
    coin = next(s for s in base.index if s not in ("BTC/USDT", "ETH/USDT"))
    price = float(base.loc[coin, "close"]) * 1.5                                # comprou 50% acima: está 33% abaixo do pago
    write_position(workdir, coin, price)

    first = pipeline.analyze(RUN_TS, record_state=True)
    pos = first["positions"].iloc[0]
    assert pos["symbol"] == coin and pos["action"] == ACTION_SELL and pos["state_rule"] == "STOP"
    assert len(first["position_changes"]) == 1

    sent: list[list[str]] = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF-segredo")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setattr(pipeline, "send_messages", lambda settings, texts: sent.append(list(texts)))
    assert pipeline._notify(first, RUN_TS.to_pydatetime(), dry_run=False, record_state=True) == 0
    assert any("MUDANÇA DE ESTADO" in t for t in sent[0])
    assert not any("123456:ABC-DEF-segredo" in t or "987654321" in t for t in sent[0])
    assert len(read_notifications(workdir / "data" / "state" / "notifications.parquet")) == 1

    second = pipeline.analyze(RUN_TS + pd.Timedelta(days=0), record_state=True)  # mesma situação no dia seguinte (mesmo dado)
    assert second["position_changes"].empty                                      # não repete o aviso
    sent.clear()
    assert pipeline._notify(second, RUN_TS.to_pydatetime(), dry_run=False, record_state=True) == 0
    assert not any("MUDANÇA DE ESTADO" in t for t in sent[0])
    history = read_state_log(workdir / "data" / "state" / "position_states.parquet")
    assert history["changed"].sum() == 1
    out = capsys.readouterr().out + str(sent)
    assert "123456:ABC-DEF-segredo" not in out


def test_failed_send_is_retried_on_the_next_run(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_market()
    base = pipeline.analyze(RUN_TS)["signals"].set_index("symbol")
    coin = next(s for s in base.index if s not in ("BTC/USDT", "ETH/USDT"))
    price = float(base.loc[coin, "close"]) * 2.0
    write_position(workdir, coin, price)
    first = pipeline.analyze(RUN_TS, record_state=True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF-segredo")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

    def boom(settings: object, texts: list[str]) -> None:
        raise pipeline.TelegramError("falhou")

    monkeypatch.setattr(pipeline, "send_messages", boom)
    assert pipeline._notify(first, RUN_TS.to_pydatetime(), dry_run=False, record_state=True) == 2
    assert read_notifications(workdir / "data" / "state" / "notifications.parquet").empty   # nada marcado como enviado
    assert len(pipeline.analyze(RUN_TS, record_state=True)["position_changes"]) == 1       # reenvia na próxima execução


# ------------------------------------------------------------------------------------------------- branch `state`

def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_state_branch_is_created_pushed_and_pulled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote = tmp_path / "remote.git"
    git(["init", "--bare", "-q", str(remote)], tmp_path)
    mine, other = tmp_path / "mine", tmp_path / "other"
    for repo in (mine, other):
        git(["init", "-q", str(repo)], tmp_path)
        git(["config", "user.email", "t@example.com"], repo)
        git(["config", "user.name", "t"], repo)
        git(["remote", "add", "origin", str(remote)], repo)
        (repo / "x.txt").write_text("x", encoding="utf-8")
        git(["add", "-A"], repo)
        git(["commit", "-q", "-m", "base"], repo)

    monkeypatch.chdir(mine)
    assert "criada" in state_sync.init()
    (mine / "data" / "state" / "positions.parquet").write_bytes(b"dados")
    assert state_sync.push("posições: add") is True
    assert state_sync.push("nada mudou") is False                              # nada a enviar
    assert "state" in git(["branch", "--list", "state"], remote)               # a branch existe no remoto

    monkeypatch.chdir(other)
    assert "ligado" in state_sync.init()
    assert (other / "data" / "state" / "positions.parquet").read_bytes() == b"dados"
    (other / "data" / "state" / "positions.parquet").write_bytes(b"dados2")
    assert state_sync.push("outra máquina") is True
    monkeypatch.chdir(mine)
    assert state_sync.pull() is True
    assert (mine / "data" / "state" / "positions.parquet").read_bytes() == b"dados2"
    assert git(["rev-parse", "--abbrev-ref", "HEAD"], mine) != "state"          # a branch do trabalho não foi tocada
