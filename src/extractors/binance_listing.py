"""Lista de pares `*USDT` que já existiram na Binance spot (inclusive os deslistados), pelo bucket público de dados.

`exchangeInfo` só traz os pares ativos hoje; o bucket `data.binance.vision` guarda um diretório por par que já
negociou, e o histórico de klines dos deslistados continua disponível na API pública (verificado com LUNAUSDT,
BTTUSDT e EOSUSDT). I/O somente em `fetch_usdt_symbols`; `parse_listing` é pura.

Limitações: o bucket não informa a data nem o motivo da deslistagem; renomeações e migrações (ex.: LUNA para LUNC)
aparecem como pares diferentes.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .base_extractor import ExtractorError
from .http import get_text

LISTING_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
PREFIX = "data/spot/monthly/klines/"
PAGE_SIZE = 1000
QUOTE = "USDT"
_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
_SYMBOL = re.compile(r"^[A-Z0-9]{1,20}$")


def parse_listing(xml: str) -> tuple[list[str], str | None]:
    """Símbolos (ex.: `BTCUSDT`) de uma página da listagem e o marcador da próxima (None na última)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ExtractorError(f"listagem de símbolos inválida: {exc}") from exc
    prefixes = [e.text or "" for e in root.findall("s3:CommonPrefixes/s3:Prefix", _NS)]
    symbols = [p[len(PREFIX):].strip("/") for p in prefixes if p.startswith(PREFIX)]
    truncated = (root.findtext("s3:IsTruncated", default="false", namespaces=_NS) or "false").lower() == "true"
    marker = (root.findtext("s3:NextMarker", namespaces=_NS) or (prefixes[-1] if prefixes else None)) if truncated else None
    return [s for s in symbols if _SYMBOL.match(s)], marker


def usdt_symbols(symbols: list[str]) -> list[str]:
    """Só os pares cotados em USDT, no formato `BASE/USDT`, sem repetição, em ordem alfabética."""
    return sorted({f"{s[: -len(QUOTE)]}/{QUOTE}" for s in symbols if s.endswith(QUOTE) and len(s) > len(QUOTE)})


def fetch_usdt_symbols() -> list[str]:
    """Todos os pares `BASE/USDT` listados no bucket público (rede)."""
    found: list[str] = []
    marker: str | None = None
    while True:
        params: dict[str, str | int] = {"delimiter": "/", "prefix": PREFIX, "max-keys": PAGE_SIZE}
        if marker is not None:
            params["marker"] = marker
        page, marker = parse_listing(get_text(LISTING_URL, params, min_interval=0.2))
        found.extend(page)
        if marker is None:
            break
    if not found:
        raise ExtractorError("listagem de símbolos vazia")
    return usdt_symbols(found)
