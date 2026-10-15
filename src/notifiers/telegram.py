"""Envio de mensagens pelo Telegram Bot API (`sendMessage`). Somente envio: sem ordens, sem exchange.

Garantias:
    - timeout por tentativa e no máximo `retries` tentativas, com espera exponencial (2, 4, 8 s, teto de 30 s);
    - HTTP 429: espera o `retry_after` informado pelo Telegram (acima de 60 s desiste); 5xx e falha de rede
      são tentados de novo; 400/401/403/404 (token ou chat errado) não, porque repetir não adianta;
    - uma pausa de 1 s entre mensagens (o Telegram limita a cerca de 1 por segundo por chat);
    - cada texto tem no máximo 4096 caracteres (a divisão é feita por `transformers.notification`);
    - o token está na URL da API, então NENHUMA mensagem de erro leva a URL, o token ou o corpo cru da
      resposta: tudo passa por `_scrub`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

API_URL = "https://api.telegram.org"
MAX_LENGTH = 4096
MAX_BACKOFF = 30.0
MAX_RETRY_AFTER = 60.0
PAUSE_BETWEEN_MESSAGES = 1.0
ENV_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_CHAT_ID = "TELEGRAM_CHAT_ID"

_NO_RETRY = {400, 401, 403, 404}


class TelegramError(RuntimeError):
    """Falha no envio. A mensagem nunca contém o token."""


@dataclass(frozen=True)
class TelegramSettings:
    token: str = field(repr=False)  # fora do repr: não vaza em logs nem em tracebacks de dataclass
    chat_id: str


def settings_from_env(env: Mapping[str, str]) -> TelegramSettings | None:
    """Configuração a partir de TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID; None se faltar qualquer uma."""
    token = env.get(ENV_TOKEN, "").strip()
    chat_id = env.get(ENV_CHAT_ID, "").strip()
    return TelegramSettings(token, chat_id) if token and chat_id else None


def _scrub(text: str, token: str) -> str:
    """Remove o token (e a forma `bot<token>` da URL) de qualquer texto que vá para log ou exceção."""
    return text.replace(f"bot{token}", "bot***").replace(token, "***") if token else text


def _reason(exc: urllib.error.HTTPError, token: str) -> tuple[str, float | None]:
    """(descrição do Telegram sem o token, retry_after em segundos se houver)."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (ValueError, OSError):
        return "", None
    if not isinstance(body, dict):
        return "", None
    params = body.get("parameters")
    retry_after = params.get("retry_after") if isinstance(params, dict) else None
    description = body.get("description")
    return _scrub(str(description), token) if description is not None else "", (
        float(retry_after) if isinstance(retry_after, int | float) else None
    )


def _post(settings: TelegramSettings, text: str, retries: int, timeout: float) -> None:
    payload = json.dumps({"chat_id": settings.chat_id, "text": text, "disable_web_page_preview": True}).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/bot{settings.token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(1, retries + 1):
        wait = min(2.0**attempt, MAX_BACKOFF)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if isinstance(body, dict) and body.get("ok") is True:
                return
            raise TelegramError("Telegram respondeu sem confirmar o envio")
        except urllib.error.HTTPError as exc:
            description, retry_after = _reason(exc, settings.token)
            if exc.code in _NO_RETRY:
                raise TelegramError(f"Telegram recusou o envio (HTTP {exc.code}): {description or 'sem detalhe'}") from None
            if attempt == retries:
                raise TelegramError(f"Telegram falhou depois de {retries} tentativas (HTTP {exc.code})") from None
            if exc.code == 429 and retry_after is not None:
                if retry_after > MAX_RETRY_AFTER:
                    raise TelegramError(f"Telegram pediu espera de {retry_after:.0f}s (HTTP 429); desisti") from None
                wait = retry_after
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == retries:
                raise TelegramError(
                    f"Telegram inacessível depois de {retries} tentativas: {_scrub(type(exc).__name__, settings.token)}"
                ) from None
        except (ValueError, UnicodeDecodeError):
            raise TelegramError("Telegram respondeu algo que não é JSON") from None
        time.sleep(wait)


def send_messages(
    settings: TelegramSettings, texts: Sequence[str], *, retries: int = 3, timeout: float = 15.0
) -> None:
    """Envia cada texto em ordem. Levanta TelegramError (sem o token) se algum não for entregue."""
    for i, text in enumerate(texts):
        if not text.strip():
            raise TelegramError("mensagem vazia")
        if len(text) > MAX_LENGTH:
            raise TelegramError(f"mensagem com {len(text)} caracteres (máximo {MAX_LENGTH})")
        if i > 0:
            time.sleep(PAUSE_BETWEEN_MESSAGES)
        _post(settings, text, retries, timeout)
