"""GET JSON com retry e backoff exponencial (stdlib, síncrono). Usado só dentro de `fetch`."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base_extractor import ExtractorError

RETRYABLE_STATUS = {418, 429, 500, 502, 503, 504}
USER_AGENT = "crypto-analyzer/0.1"


def get_json(
    url: str,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    *,
    retries: int = 5,
    timeout: float = 30.0,
) -> Any:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(url + query, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt == retries:
                raise ExtractorError(f"GET {url} falhou: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries:
                raise ExtractorError(f"GET {url} falhou: {exc}") from exc
        time.sleep(min(2**attempt, 30))
    raise ExtractorError(f"GET {url} falhou após {retries} tentativas")
