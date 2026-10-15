"""get_json: API indisponível, timeout, backoff, Retry-After, limite por host, JSON inválido. Sem rede real."""

from __future__ import annotations

import io
import json
import urllib.error
from collections.abc import Callable
from email.message import Message
from typing import Any

import pytest

from src.extractors import ExtractorError
from src.extractors import http

URL = "https://api.exemplo.test/v1/dados"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(URL, code, "erro", headers, io.BytesIO(b""))


class Script:
    """Substitui urlopen: cada chamada consome o próximo item (exceção a lançar ou corpo a devolver)."""

    def __init__(self, steps: list[BaseException | bytes]) -> None:
        self.steps = steps
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: Any, timeout: float | None = None) -> FakeResponse:
        self.calls.append({"url": request.full_url, "timeout": timeout, "headers": dict(request.header_items())})
        step = self.steps[min(len(self.calls), len(self.steps)) - 1]
        if isinstance(step, BaseException):
            raise step
        return FakeResponse(step)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waited: list[float] = []
    monkeypatch.setattr(http.time, "sleep", waited.append)
    monkeypatch.setattr(http, "_last_call", {})
    return waited


def install(monkeypatch: pytest.MonkeyPatch, steps: list[BaseException | bytes]) -> Script:
    script = Script(steps)
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    return script


def test_api_unavailable_gives_up_after_limited_retries_with_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    script = install(monkeypatch, [urllib.error.URLError("sem rota")])
    with pytest.raises(ExtractorError):
        http.get_json(URL, retries=4)
    assert len(script.calls) == 4
    assert sleeps == [2.0, 4.0, 8.0]


def test_http_503_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, [http_error(503), json.dumps({"ok": 1}).encode()])
    assert http.get_json(URL) == {"ok": 1}
    assert len(script.calls) == 2
    assert sleeps == [2.0]


def test_timeout_is_passed_and_retried(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, [TimeoutError("timed out")])
    with pytest.raises(ExtractorError, match="timed out"):
        http.get_json(URL, retries=3, timeout=7.5)
    assert [c["timeout"] for c in script.calls] == [7.5, 7.5, 7.5]


def test_client_error_is_not_retried(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, [http_error(404)])
    with pytest.raises(ExtractorError, match="HTTP 404"):
        http.get_json(URL)
    assert len(script.calls) == 1
    assert sleeps == []


def test_retry_after_is_honoured_on_429(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, [http_error(429, "7"), b"[]"])
    assert http.get_json(URL) == []
    assert sleeps == [7.0]
    assert len(script.calls) == 2


def test_long_ban_gives_up_immediately(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    script = install(monkeypatch, [http_error(418, "3600")])
    with pytest.raises(ExtractorError, match="Retry-After"):
        http.get_json(URL)
    assert len(script.calls) == 1
    assert sleeps == []


def test_invalid_json_is_an_extractor_error(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    install(monkeypatch, [b"<html>manutencao</html>"])
    with pytest.raises(ExtractorError, match="JSON"):
        http.get_json(URL)


def test_min_interval_spaces_calls_to_the_same_host(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(http.time, "monotonic", lambda: clock["now"])
    install(monkeypatch, [b"{}"])
    http.get_json(URL, min_interval=1.0)
    clock["now"] += 0.25
    http.get_json(URL, min_interval=1.0)
    assert sleeps == [pytest.approx(0.75)]
    clock["now"] += 5.0
    http.get_json(URL, min_interval=1.0)
    assert sleeps == [pytest.approx(0.75)]


def test_api_key_never_appears_in_errors(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    install(monkeypatch, [http_error(500)])
    secret = "CHAVE-SECRETA-123"
    for call in (
        lambda: http.get_json(URL, headers={"x-cg-demo-api-key": secret}, retries=2),
        lambda: http.get_json(URL, params={"a": 1}, headers={"x-cg-demo-api-key": secret}, retries=1),
    ):
        with pytest.raises(ExtractorError) as err:
            call()
        assert secret not in str(err.value)


def test_success_returns_parsed_json(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    install(monkeypatch, [json.dumps([1, 2, 3]).encode()])
    call: Callable[[], object] = lambda: http.get_json(URL, params={"limit": 3})
    assert call() == [1, 2, 3]
