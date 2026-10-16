"""GET (JSON ou bytes) com timeout, tentativas limitadas, backoff exponencial e respeito ao limite da API.

Stdlib, síncrono; usado só dentro de `fetch`. Garantias:
    - cada tentativa tem timeout (padrão 30 s) e são no máximo `retries` tentativas;
    - entre tentativas espera 2^n s (teto de 30 s); em 429/418 a espera é o `Retry-After` da resposta
      e, se ele passar de `MAX_RETRY_AFTER` (ban longo), desiste na hora em vez de insistir;
    - `min_interval` espaça as chamadas ao mesmo host (cada fonte declara o seu limite);
    - corpo que não é JSON vira ExtractorError (`get_json`);
    - `get_bytes(..., missing_ok=True)` devolve None em HTTP 404 (arquivo que não existe na fonte);
    - a mensagem de erro leva só a URL sem parâmetros e o status, nunca cabeçalhos (chaves de API).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base_extractor import ExtractorError

RETRYABLE_STATUS = {418, 429, 500, 502, 503, 504}
USER_AGENT = "crypto-analyzer/0.1"
MAX_BACKOFF = 30.0
MAX_RETRY_AFTER = 60.0

_last_call: dict[str, float] = {}
_throttle_lock = threading.Lock()  # downloads em massa usam várias threads


def _throttle(host: str, min_interval: float) -> None:
    """Espera o que faltar para respeitar `min_interval` desde a última chamada ao mesmo host."""
    if min_interval <= 0:
        _last_call[host] = time.monotonic()
        return
    with _throttle_lock:
        wait = _last_call.get(host, float("-inf")) + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers is not None else None
    try:
        return None if value is None else max(float(value), 0.0)
    except ValueError:
        return None


def get_json(
    url: str,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    *,
    retries: int = 5,
    timeout: float = 30.0,
    min_interval: float = 0.0,
) -> Any:
    body = get_bytes(url, params, headers, retries=retries, timeout=timeout, min_interval=min_interval)
    if body is None:  # inalcançável: sem missing_ok, 404 já vira ExtractorError
        raise ExtractorError(f"GET {url} falhou: resposta vazia")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtractorError(f"GET {url} falhou: resposta não é JSON válido") from exc


def get_bytes(
    url: str,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    *,
    retries: int = 5,
    timeout: float = 30.0,
    min_interval: float = 0.0,
    missing_ok: bool = False,
) -> bytes | None:
    """Corpo bruto da resposta. Com `missing_ok`, HTTP 404 devolve None em vez de erro (sem nova tentativa)."""
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(url + query, headers={"User-Agent": USER_AGENT, **(headers or {})})
    host = urllib.parse.urlsplit(url).netloc
    for attempt in range(1, retries + 1):
        wait = min(2.0**attempt, MAX_BACKOFF)
        _throttle(host, min_interval)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body: bytes = resp.read()
            return body
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and missing_ok:
                return None
            if exc.code not in RETRYABLE_STATUS or attempt == retries:
                raise ExtractorError(f"GET {url} falhou: HTTP {exc.code}") from exc
            asked = _retry_after(exc) if exc.code in (418, 429) else None
            if asked is not None:
                if asked > MAX_RETRY_AFTER:
                    raise ExtractorError(f"GET {url} falhou: HTTP {exc.code}, limite excedido (Retry-After {asked:.0f}s)") from exc
                wait = asked
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == retries:
                raise ExtractorError(f"GET {url} falhou: {exc}") from exc
        time.sleep(wait)
    raise ExtractorError(f"GET {url} falhou após {retries} tentativas")
