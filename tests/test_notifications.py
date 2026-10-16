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
    data_notes,
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


def coin(symbol: str, **over: Any) -> dict[str, Any]:
    """Uma linha de daily_signals (só as colunas que o formatador lê)."""
    row: dict[str, Any] = {
        "symbol": symbol, "timestamp": LAST, "alert": pd.NA, "panic": False, "selected": False, "candidate_rank": pd.NA,
        "opportunity": "AGUARDAR", "score": 40.0, "allocation_brl": 0.0, "allocation_note": pd.NA,
        "reasons": [], "risks": [], "blockers": ["mercado defensivo: Bitcoin abaixo da média"],
    }
    row.update(over)
    return row


def pick(symbol: str, rank: int, amount: float, **over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = dict(
        selected=True, candidate_rank=rank, opportunity="BOA_RELATIVA", score=78.0, allocation_brl=amount,
        reasons=["tendência de alta: preço 12,0% acima da média de 200 dias", "momento positivo: +8,0% em 30 dias e +20,0% em 90 dias",
                 "liquidez adequada: US$ 900 mi negociados por dia", "4 de 4 condições favoráveis: acima da média de 200 dias"],
        risks=["volatilidade elevada: o preço oscila cerca de 95% ao ano"], blockers=[],
    )
    return coin(symbol, **{**fields, **over})


def signals(*rows: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(rows).astype({"alert": "string", "allocation_note": "string", "candidate_rank": "Int64"})


def rec(total: float = 0.0, budget: float = 100.0, **over: Any) -> pd.DataFrame:
    row: dict[str, Any] = {
        "run_ts": NOW, "data_day": LAST, "budget_brl": budget, "regime": "FAVORAVEL", "total_brl": total,
        "unallocated_brl": budget - total, "notes": [], "data_notes": [], "evidence": "No teste fora da amostra a seleção não superou o comprar e segurar.",
    }
    row.update(over)
    return pd.DataFrame([row])


def report(sig: pd.DataFrame, summary: pd.DataFrame) -> str:
    texts = format_report(sig, summary, now=NOW, recommended=RECOMMENDED)
    assert validate_messages(texts) == []
    return "\n\n".join(texts)


# ------------------------------------------------------------------------------ formatação

def test_message_with_picks_uses_only_computed_numbers() -> None:
    sig = signals(pick("ETH/USDT", 1, 30.0), pick("SOL/USDT", 2, 15.0, opportunity="MODERADA", score=61.0), coin("BTC/USDT"))
    text = report(sig, rec(total=45.0))
    assert text.startswith("📊 CRIPTO — ANÁLISE DO DIA")
    assert "15/10/2026 21:10 (Fortaleza)" in text  # 00:10 UTC = 21:10 em Fortaleza, ainda dia 15
    assert "Dados: fechamento diário de 15/10 (UTC), em dia." in text
    assert "Orçamento disponível na simulação: R$ 100" in text
    assert "Mercado: favorável" in text
    assert "1. ETH — Aporte sugerido: R$ 30" in text and "2. SOL — Aporte sugerido: R$ 15" in text
    assert "Classificação: boa oportunidade relativa (score 78 de 100)" in text
    assert "Classificação: oportunidade moderada (score 61 de 100)" in text
    assert "Motivo: Tendência de alta (acima da média de 200 dias), momento positivo (subiu em 30 e 90 dias) e liquidez adequada." in text
    assert "Atenção: volatilidade elevada: o preço oscila cerca de 95% ao ano." in text
    assert "Total sugerido: R$ 45 de R$ 100." in text and "Saldo não alocado: R$ 55." in text
    assert "Decisão: considerar um aporte de R$ 45, ou aguardar" in text
    assert "não garantias de valorização" in text and "não probabilidade de lucro" in text
    assert "BTC —" not in text  # moeda não selecionada não aparece como oportunidade
    assert len(text) < 2500


def test_single_opportunity_shows_only_one() -> None:
    text = report(signals(pick("SOL/USDT", 1, 20.0), coin("BTC/USDT"), coin("ETH/USDT")), rec(total=20.0))
    assert "1. SOL" in text and "2." not in text


def test_no_opportunity_uses_the_fixed_sentence_and_says_why() -> None:
    sig = signals(coin("BTC/USDT"), coin("ETH/USDT"), coin("SOL/USDT", blockers=["tendência de baixa: preço 5% abaixo"]))
    text = report(sig, rec(regime="DEFENSIVO"))
    assert (
        "Hoje não encontrei oportunidades suficientemente boas dentro dos critérios configurados. "
        "Aporte sugerido: R$ 0 de R$ 100. O orçamento permanece sem alocação." in text
    )
    assert "Mercado: defensivo" in text
    assert "Principais motivos: mercado defensivo (2 de 3 moedas)" in text
    assert "Melhores oportunidades" not in text


def test_candidates_without_executable_amount_are_explained() -> None:
    sig = signals(pick("SOL/USDT", 1, 0.0, allocation_note="aporte de R$ 8 fica abaixo da ordem mínima de R$ 10: impraticável"))
    text = report(sig, rec(total=0.0, budget=20.0))
    assert "Aporte sugerido: R$ 0 de R$ 20." in text
    assert "SOL: aporte de R$ 8 fica abaixo da ordem mínima de R$ 10: impraticável" in text


def test_budget_notes_and_data_limits_are_shown() -> None:
    notes = ["O modelo teria uma exposição-alvo de R$ 120; a sugestão fica limitada ao orçamento de R$ 100."]
    limits = ["falha na coleta de preços (ETH): essas moedas não podem ser recomendadas hoje"]
    text = report(signals(pick("SOL/USDT", 1, 40.0)), rec(total=40.0, notes=notes, data_notes=limits))
    assert notes[0] in text
    assert "⚠️ Limitações desta análise" in text and limits[0] in text


def test_stale_data_is_flagged_in_the_header() -> None:
    text = report(signals(coin("BTC/USDT")), rec(data_day=pd.Timestamp("2026-10-13", tz="UTC")))
    assert "ATRASADO 2 dia(s)" in text and "Limitações desta análise" in text


def test_essential_alerts_only_sma200_turns_and_panic() -> None:
    sig = signals(coin("BTC/USDT", alert="VENDER AGORA"), coin("ETH/USDT"), coin("SOL/USDT", alert="NO RADAR", panic=True))
    text = report(sig, rec())
    assert "BTC saiu da tendência de alta hoje (regra principal SMA 200)." in text
    assert "SOL chegou perto" not in text  # outras moedas não poluem a mensagem
    assert "Pânico em SOL" in text and "É só aviso" in text


def test_message_never_invents_entry_points_or_certainty() -> None:
    text = report(signals(pick("SOL/USDT", 1, 40.0)), rec(total=40.0)).lower()
    for forbidden in ("ponto de entrada", "venda tudo", "alvo de preço", "garantido", "muito bom para comprar", "você deve"):
        assert forbidden not in text


def test_report_fits_telegram_and_never_lists_dozens_of_coins() -> None:
    rows = [coin(f"C{i:03d}/USDT") for i in range(300)] + [pick("SOL/USDT", 1, 40.0)]
    texts = format_report(signals(*rows), rec(total=40.0), now=NOW, recommended=RECOMMENDED)
    assert all(0 < len(t) <= TELEGRAM_LIMIT for t in texts)
    assert "C001" not in "".join(texts)


def test_data_notes_summarize_failures_and_unavailable_coins() -> None:
    available = pd.DataFrame({"symbol": ["BTC/USDT", "SOL/USDT"], "available": [True, False]})
    errors = pd.DataFrame([{"source": "binance", "scope": "SOL/USDT", "detail": "HTTP 503"},
                           {"source": "coingecko", "scope": "MARKET", "detail": "x"}])
    notes = data_notes(available, errors)
    assert any("falha na coleta de preços (SOL)" in n for n in notes)
    assert any("fonte secundária fora do ar (coingecko)" in n for n in notes)
    assert any("1 moeda(s) sem dado confiável hoje (SOL)" in n for n in notes)
    assert data_notes(available.assign(available=True), None) == []


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
    assert "CRIPTO — ANÁLISE DO DIA" in out
    assert "Orçamento disponível na simulação: R$ 100" in out
    assert "Validação histórica:" in out


def test_notify_without_credentials_fails_loudly(workdir: Path) -> None:
    assert pipeline.main(["--offline", "--notify"]) == 2


def test_notify_sends_the_validated_messages(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    sent: list[list[str]] = []
    monkeypatch.setattr(pipeline, "send_messages", lambda settings, texts: sent.append(list(texts)))
    assert pipeline.main(["--offline", "--notify"]) == 0
    assert len(sent) == 1 and all(len(t) <= TELEGRAM_LIMIT for t in sent[0])
    assert TOKEN not in "".join(sent[0])


def test_send_failure_turns_the_run_red(workdir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

    def boom(settings: TelegramSettings, texts: list[str]) -> None:
        raise TelegramError("Telegram inacessível depois de 3 tentativas")

    monkeypatch.setattr(pipeline, "send_messages", boom)
    assert pipeline.main(["--offline", "--notify"]) == 2
    assert TOKEN not in caplog.text


def test_pipeline_failure_sends_a_short_redacted_alert(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setenv("COINGECKO_API_KEY", "CG-chave-secreta")
    sent: list[list[str]] = []
    monkeypatch.setattr(pipeline, "send_messages", lambda settings, texts: sent.append(list(texts)))

    def broken(today: pd.Timestamp, **kwargs: Any) -> dict[str, pd.DataFrame]:
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

    def broken(today: pd.Timestamp, **kwargs: Any) -> dict[str, pd.DataFrame]:
        raise KeyError("coluna")

    monkeypatch.setattr(pipeline, "analyze", broken)
    assert pipeline.main(["--offline", "--notify"]) == 1  # sem credenciais: não tenta enviar
    assert sent == []

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    assert pipeline.main(["--offline", "--notify"]) == 1
    assert len(sent) == 1 and "KeyError" in sent[0][0]


def test_dry_run_never_sends_an_error_alert(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    sent: list[Callable[..., Any]] = []
    monkeypatch.setattr(pipeline, "send_messages", lambda *a, **k: sent.append(lambda: None))
    monkeypatch.setattr(pipeline, "analyze", lambda today, **kw: (_ for _ in ()).throw(ExtractorError("x")))
    assert pipeline.main(["--offline", "--dry-run", "--notify"]) == 1
    assert sent == []
