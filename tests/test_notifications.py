"""Telegram: formatação (pura), divisão em 4096, dry-run sem token, erro de envio e retry. Sem rede."""

from __future__ import annotations

import io
import json
import urllib.error
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src import pipeline
from src.config import UNIVERSE
from src.extractors import ExtractorError
from src.loaders.market_store import write_ohlcv
from src.notifiers import TelegramError, TelegramSettings, send_messages, settings_from_env
from src.notifiers import telegram
from src.transformers.notification import (
    TELEGRAM_LIMIT,
    format_error,
    format_report,
    redact,
    split_message,
    validate_messages,
)
from tests.helpers import make_candles, ramp

NOW = pd.Timestamp("2026-10-16 00:10", tz="UTC")  # logo depois do fechamento do candle de 15/10
LAST = pd.Timestamp("2026-10-15", tz="UTC")
RECOMMENDED = ("BTC/USDT", "ETH/USDT")
TOKEN = "123456:ABC-DEF-segredo"


def signal_row(symbol: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": symbol, "timestamp": LAST, "close": 81682.0 if symbol == "BTC/USDT" else 2421.6,
        "sma_200": 72243.2 if symbol == "BTC/USDT" else 2141.5, "stage": "COMPRAR", "stage_reason": pd.NA,
        "alert": pd.NA, "panic": False, "regime_up": True, "fng_value": 53,
    }
    row.update(over)
    return row


def signals(*rows: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    return frame.astype({"stage_reason": "string", "alert": "string"})


def forecast_rows(beats: bool = False, coverage_ok: bool = True) -> pd.DataFrame:
    rows = []
    for symbol in RECOMMENDED:
        for h, lo, hi in ((1, -2.4, 2.2), (7, -7.4, 6.6), (30, -16.7, 15.2)):
            rows.append({"symbol": symbol, "horizon_days": h, "role": "MODELO", "p10_pct": lo, "p90_pct": hi,
                         "beats_baseline": beats, "coverage_ok": coverage_ok, "coverage": 0.83})
    return pd.DataFrame(rows)


def report(sig: pd.DataFrame, fc: pd.DataFrame | None = None, errors: pd.DataFrame | None = None) -> str:
    texts = format_report(sig, forecast_rows() if fc is None else fc, now=NOW, recommended=RECOMMENDED,
                          regime_symbol="BTC/USDT", max_stale_days=1, source_errors=errors)
    assert validate_messages(texts) == []
    return "\n\n".join(texts)


def both(**over: Any) -> pd.DataFrame:
    return signals(signal_row("BTC/USDT", **over), signal_row("ETH/USDT", **over))


# ------------------------------------------------------------------------------ formatação

def test_buy_message_has_everything_a_phone_needs() -> None:
    text = report(both())
    assert "16/10/2026" not in text or "Fortaleza" in text
    assert "15/10/2026 21:10 (Fortaleza)" in text  # 00:10 UTC = 21:10 em Fortaleza, ainda dia 15
    assert "candle diário fechado de 15/10 (UTC), em dia" in text
    assert "🟢 BTC — COMPRAR" in text and "🟢 ETH — COMPRAR" in text
    assert "US$ 81.682" in text and "fechamento diário de 15/10" in text
    assert "SMA 200: US$ 72.243" in text and "13,1% acima da média" in text
    assert "Filtro do BTC: BTC acima da SMA 200 dele (ok)" in text
    assert "Sustenta: fechou acima da SMA 200." in text
    assert "Invalida: fechar abaixo de US$ 72.243 (SMA 200 atual)." in text
    assert "ETH fechar" not in text and "ou o BTC fechar abaixo de US$ 72.243" in text  # a invalidação do ETH cita o BTC
    assert "1d −2% a +2%" in text and "7d −7% a +7%" in text and "30d −17% a +15%" in text
    assert "Sem vantagem demonstrada sobre o preço de hoje" in text
    assert "NÃO CONFIÁVEL" not in text and "DADOS PARCIAIS" not in text
    assert "Nenhuma moeda em pânico." in text
    assert "não recomendação de investimento" in text


def test_message_never_invents_entry_points_or_advice() -> None:
    text = report(both()).lower()
    for forbidden in ("ponto de entrada", "compre ", "venda tudo", "alvo", "stop loss", "você deve"):
        assert forbidden not in text


@pytest.mark.parametrize(
    ("over", "label", "snippet"),
    [
        ({"stage": "PREPARAR", "close": 71000.0}, "🟡 BTC — PREPARAR", "Vira COMPRAR: fechar acima de US$ 72.243"),
        ({"stage": "NEUTRO", "close": 60000.0, "regime_up": False}, "⚪ BTC — NEUTRO", "Sustenta: fechou abaixo da SMA 200."),
        ({"stage": "NEUTRO", "alert": "VENDER AGORA", "close": 60000.0, "regime_up": False}, "🔴 BTC — VENDER", "Volta a COMPRAR: fechar acima de US$ 72.243"),
    ],
)
def test_each_signal_has_its_label_and_conditions(over: dict[str, Any], label: str, snippet: str) -> None:
    text = report(signals(signal_row("BTC/USDT", **over), signal_row("ETH/USDT")))
    assert label in text
    assert snippet in text
    assert "NaN" not in text


def test_unavailable_has_reason_and_no_signal_or_forecast() -> None:
    reason = "dado desatualizado: último candle em 10/10/2026 (5 dias de atraso)"
    sig = signals(signal_row("BTC/USDT", stage="INDISPONÍVEL", stage_reason=reason), signal_row("ETH/USDT"))
    text = report(sig)
    assert "⚫ BTC — INDISPONÍVEL" in text
    assert reason in text
    assert "Sem sinal e sem previsão para esta moeda hoje." in text
    assert "DADOS PARCIAIS" in text
    assert "🟢 ETH — COMPRAR (NÃO CONFIÁVEL: dados parciais)" in text  # dado parcial: nenhum sinal vira "confiável"


def test_partial_data_marks_every_signal_as_unreliable_and_lists_the_failure() -> None:
    errors = pd.DataFrame([{"source": "binance", "scope": "ETH/USDT", "detail": "HTTP 503"}])
    text = report(both(), errors=errors)
    assert "DADOS PARCIAIS" in text
    assert text.count("NÃO CONFIÁVEL") == 2
    assert "Falha na coleta de preços (ETH)" in text


def test_stale_data_is_flagged_in_the_header() -> None:
    old = pd.Timestamp("2026-10-13", tz="UTC")
    text = report(both(timestamp=old))
    assert "ATRASADO 2 dia(s)" in text
    assert "DADOS PARCIAIS" in text


def test_secondary_source_failure_does_not_discredit_price_signals() -> None:
    errors = pd.DataFrame([{"source": "coingecko", "scope": "MARKET", "detail": "resposta incompleta"}])
    text = report(both(), errors=errors)
    assert "Fonte secundária fora do ar (coingecko)" in text
    assert "os sinais por preço seguem valendo" in text
    assert "DADOS PARCIAIS" not in text and "NÃO CONFIÁVEL" not in text


def test_panic_is_a_separate_section_without_buy_recommendation() -> None:
    sig = signals(signal_row("BTC/USDT"), signal_row("ETH/USDT"), signal_row("SOL/USDT", stage="NEUTRO", panic=True, close=100.0, sma_200=90.0))
    text = report(sig)
    section = text.split("⚠️ Aviso de pânico")[1]
    assert "Pânico em: SOL" in section
    assert "não é recomendação de compra" in text
    assert "SOL" not in text.split("⚠️ Aviso de pânico")[0]  # SOL só aparece na seção de pânico


def test_other_coins_only_appear_when_something_relevant_changed() -> None:
    quiet = signals(signal_row("BTC/USDT"), signal_row("ETH/USDT"), signal_row("SOL/USDT", stage="NEUTRO", close=100.0, sma_200=90.0))
    text = report(quiet)
    assert "SOL" not in text and "Outras moedas" not in text and "autorizar compra" not in text

    moved = signals(signal_row("BTC/USDT"), signal_row("ETH/USDT"),
                    signal_row("SOL/USDT", alert="COMPRAR AGORA", close=100.0, sma_200=90.0))
    text = report(moved)
    assert "SOL: entrou em tendência de alta" in text
    assert "Monitorar não é autorizar compra: a regra só recomenda BTC e ETH." in text


def test_forecast_variants() -> None:
    assert "Previsão: indisponível." in report(both(), fc=forecast_rows().iloc[0:0])
    edge = report(both(), fc=forecast_rows(beats=True))
    assert "Vantagem demonstrada sobre o preço de hoje só em: 1d, 7d, 30d." in edge
    assert "Sem vantagem demonstrada" not in edge
    off = report(both(), fc=forecast_rows(coverage_ok=False))
    assert "Faixa pouco calibrada no teste" in off and "1d 83%" in off


def test_report_is_split_to_fit_telegram_even_with_many_alerts() -> None:
    rows = [signal_row("BTC/USDT"), signal_row("ETH/USDT")]
    rows += [signal_row(f"C{i:03d}/USDT", alert="NO RADAR", stage="PREPARAR", close=10.0, sma_200=10.2) for i in range(400)]
    texts = format_report(signals(*rows), forecast_rows(), now=NOW, recommended=RECOMMENDED,
                          regime_symbol="BTC/USDT", max_stale_days=1)
    assert len(texts) > 1
    assert all(0 < len(t) <= TELEGRAM_LIMIT for t in texts)
    assert validate_messages(texts) == []


# ------------------------------------------------------------------------------ divisão e validação

def test_split_short_text_is_untouched() -> None:
    assert split_message("olá") == ["olá"]


def test_split_prefers_paragraphs_then_lines_and_loses_nothing() -> None:
    paragraphs = [f"parágrafo {i}: " + "x" * 700 for i in range(12)]
    text = "\n\n".join(paragraphs)
    parts = split_message(text, limit=2000)
    assert all(len(p) <= 2000 for p in parts)
    assert len(parts) >= 4
    assert all(p.count("parágrafo") >= 1 for p in parts)
    assert "\n\n".join(parts) == text  # nada perdido e os cortes caíram em fronteiras de parágrafo
    lines = "\n".join("linha " + "y" * 90 for _ in range(100))
    assert "\n".join(split_message(lines, limit=500)) == lines


def test_split_hard_cuts_a_single_giant_word_and_respects_the_exact_limit() -> None:
    giant = "z" * 9000
    parts = split_message(giant, limit=4096)
    assert [len(p) for p in parts] == [4096, 4096, 808]
    exact = "a" * 4096
    assert split_message(exact) == [exact]
    assert [len(p) for p in split_message("a" * 4097)] == [4096, 1]


def test_validation_catches_every_problem() -> None:
    assert validate_messages([]) == ["nenhuma mensagem gerada"]
    assert any("vazia" in p for p in validate_messages(["  "]))
    assert any("limite" in p for p in validate_messages(["a" * 5000]))
    assert any("segredo" in p for p in validate_messages([f"token {TOKEN}"], [TOKEN]))
    assert any("nan" in p for p in validate_messages(["preço nan hoje"]))
    assert any("None" in p for p in validate_messages(["sinal None"]))
    assert any("<NA>" in p for p in validate_messages(["motivo <NA>"]))
    assert validate_messages(["tudo certo"], [TOKEN]) == []


def test_error_alert_is_short_and_redacted() -> None:
    long_detail = f"falhou com {TOKEN} " + "x" * 2000
    texts = format_error("coleta", long_detail, now=NOW, secrets=[TOKEN])
    assert len(texts) == 1 and len(texts[0]) < 700
    assert TOKEN not in texts[0] and "***" in texts[0]
    assert "Etapa: coleta" in texts[0] and "desatualizados" in texts[0]
    assert redact("a-b-c", ["b", ""]) == "a-***-c"


# ------------------------------------------------------------------------------ envio (sem rede)

URL_PART = f"/bot{TOKEN}/sendMessage"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def http_error(code: int, body: dict[str, Any] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(f"https://api.telegram.org{URL_PART}", code, "erro", Message(),
                                  io.BytesIO(json.dumps(body or {}).encode()))


OK = json.dumps({"ok": True, "result": {}}).encode()


class Script:
    def __init__(self, steps: list[BaseException | bytes]) -> None:
        self.steps, self.calls = steps, []  # type: list[BaseException | bytes], list[dict[str, Any]]

    def __call__(self, request: Any, timeout: float | None = None) -> FakeResponse:
        self.calls.append({"url": request.full_url, "timeout": timeout, "data": json.loads(request.data.decode())})
        step = self.steps[min(len(self.calls), len(self.steps)) - 1]
        if isinstance(step, BaseException):
            raise step
        return FakeResponse(step)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waited: list[float] = []
    monkeypatch.setattr(telegram.time, "sleep", waited.append)
    return waited


def install(monkeypatch: pytest.MonkeyPatch, *steps: BaseException | bytes) -> Script:
    script = Script(list(steps))
    monkeypatch.setattr(telegram.urllib.request, "urlopen", script)
    return script


SETTINGS = TelegramSettings(TOKEN, "-1001234")


def test_settings_from_env_and_repr_hides_the_token() -> None:
    assert settings_from_env({}) is None
    assert settings_from_env({"TELEGRAM_BOT_TOKEN": TOKEN}) is None
    assert settings_from_env({"TELEGRAM_BOT_TOKEN": " ", "TELEGRAM_CHAT_ID": "1"}) is None
    settings = settings_from_env({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "42"})
    assert settings is not None and settings.chat_id == "42"
    assert TOKEN not in repr(settings)


def test_send_posts_json_with_timeout_and_pauses_between_messages(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, OK)
    send_messages(SETTINGS, ["primeira", "segunda"], timeout=9.0)
    assert [c["data"]["text"] for c in script.calls] == ["primeira", "segunda"]
    assert script.calls[0]["data"]["chat_id"] == "-1001234"
    assert script.calls[0]["timeout"] == 9.0
    assert URL_PART in script.calls[0]["url"]
    assert sleeps == [1.0]


def test_send_retries_server_errors_with_backoff(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, http_error(503), http_error(502), OK)
    send_messages(SETTINGS, ["oi"])
    assert len(script.calls) == 3
    assert sleeps == [2.0, 4.0]


def test_send_gives_up_after_limited_retries_without_leaking_the_token(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, urllib.error.URLError(f"falha em {URL_PART}"))
    with pytest.raises(TelegramError) as err:
        send_messages(SETTINGS, ["oi"], retries=3)
    assert len(script.calls) == 3
    assert TOKEN not in str(err.value) and "bot" not in str(err.value).replace("inacessível", "")
    assert TOKEN not in repr(err.value)


def test_send_timeout_is_retried_then_reported(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, TimeoutError("timed out"))
    with pytest.raises(TelegramError, match="inacessível depois de 2 tentativas"):
        send_messages(SETTINGS, ["oi"], retries=2, timeout=3.0)
    assert [c["timeout"] for c in script.calls] == [3.0, 3.0]


def test_send_honours_telegram_retry_after_and_refuses_long_waits(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, http_error(429, {"parameters": {"retry_after": 5}}), OK)
    send_messages(SETTINGS, ["oi"])
    assert sleeps == [5.0] and len(script.calls) == 2

    sleeps.clear()
    script = install(monkeypatch, http_error(429, {"parameters": {"retry_after": 3600}}))
    with pytest.raises(TelegramError, match="desisti"):
        send_messages(SETTINGS, ["oi"])
    assert len(script.calls) == 1 and sleeps == []


def test_send_does_not_retry_wrong_token_and_scrubs_the_description(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, http_error(401, {"ok": False, "description": f"Unauthorized {TOKEN}"}))
    with pytest.raises(TelegramError) as err:
        send_messages(SETTINGS, ["oi"])
    assert len(script.calls) == 1 and sleeps == []
    assert "HTTP 401" in str(err.value) and "Unauthorized" in str(err.value)
    assert TOKEN not in str(err.value)


def test_send_rejects_bad_messages_before_touching_the_network(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, OK)
    with pytest.raises(TelegramError, match="vazia"):
        send_messages(SETTINGS, [" "])
    with pytest.raises(TelegramError, match="4096"):
        send_messages(SETTINGS, ["a" * 5000])
    assert script.calls == []


def test_send_requires_a_confirmed_json_answer(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    install(monkeypatch, json.dumps({"ok": False}).encode())
    with pytest.raises(TelegramError, match="sem confirmar"):
        send_messages(SETTINGS, ["oi"])
    install(monkeypatch, b"<html>")
    with pytest.raises(TelegramError, match="não é JSON"):
        send_messages(SETTINGS, ["oi"])


# ------------------------------------------------------------------------------ pipeline

@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "COINGECKO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    yesterday = pd.Timestamp.now(tz="UTC").floor("D") - pd.Timedelta(days=1)
    write_ohlcv(make_candles({s: ramp(50, 150, 420) for s in UNIVERSE}, yesterday))
    return tmp_path


def test_dry_run_needs_no_token_and_no_network(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert pipeline.main(["--offline", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry-run: mensagem válida, nada foi enviado" in out
    assert "🟢 BTC — COMPRAR" in out
    assert "Previsão: indisponível." in out  # base sintética curta demais para prever: não inventa previsão


def test_notify_without_credentials_fails_loudly(workdir: Path) -> None:
    assert pipeline.main(["--offline", "--notify"]) == 2


def test_notify_sends_the_validated_messages(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent: list[list[str]] = []
    monkeypatch.setattr(pipeline, "send_messages", lambda settings, texts: sent.append(list(texts)))
    assert pipeline.main(["--offline", "--notify"]) == 0
    assert len(sent) == 1 and all(len(t) <= TELEGRAM_LIMIT for t in sent[0])
    assert TOKEN not in "".join(sent[0])


def test_send_failure_turns_the_run_red(workdir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    def boom(settings: TelegramSettings, texts: list[str]) -> None:
        raise TelegramError("Telegram inacessível depois de 3 tentativas")

    monkeypatch.setattr(pipeline, "send_messages", boom)
    assert pipeline.main(["--offline", "--notify"]) == 2
    assert TOKEN not in caplog.text


def test_pipeline_failure_sends_a_short_redacted_alert(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("COINGECKO_API_KEY", "CG-chave-secreta")
    sent: list[list[str]] = []
    monkeypatch.setattr(pipeline, "send_messages", lambda settings, texts: sent.append(list(texts)))

    def broken(today: pd.Timestamp) -> dict[str, pd.DataFrame]:
        raise ExtractorError(f"GET falhou: HTTP 451 com CG-chave-secreta e {TOKEN}")

    monkeypatch.setattr(pipeline, "analyze", broken)
    assert pipeline.main(["--offline", "--notify"]) == 1
    assert len(sent) == 1
    message = "".join(sent[0])
    assert "o pipeline falhou" in message and "Etapa: análise" in message and "HTTP 451" in message
    assert TOKEN not in message and "CG-chave-secreta" not in message
    assert len(message) < 700


def test_unexpected_error_also_alerts_and_no_alert_without_telegram(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[list[str]] = []
    monkeypatch.setattr(pipeline, "send_messages", lambda settings, texts: sent.append(list(texts)))

    def broken(today: pd.Timestamp) -> dict[str, pd.DataFrame]:
        raise KeyError("coluna")

    monkeypatch.setattr(pipeline, "analyze", broken)
    assert pipeline.main(["--offline", "--notify"]) == 1  # sem credenciais: não tenta enviar
    assert sent == []

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    assert pipeline.main(["--offline", "--notify"]) == 1
    assert len(sent) == 1 and "KeyError" in sent[0][0]


def test_dry_run_never_sends_an_error_alert(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent: list[Callable[..., Any]] = []
    monkeypatch.setattr(pipeline, "send_messages", lambda *a, **k: sent.append(lambda: None))
    monkeypatch.setattr(pipeline, "analyze", lambda today: (_ for _ in ()).throw(ExtractorError("x")))
    assert pipeline.main(["--offline", "--dry-run", "--notify"]) == 1
    assert sent == []
