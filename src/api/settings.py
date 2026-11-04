"""Caminhos e limites da API. Entrada de ambiente apenas na borda, nunca nas regras."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT / "frontend" / "public"
FRONTEND_DIST = ROOT / "frontend" / "dist"
MARKET_DIR = ROOT / "data" / "market"
PIT_DIR = MARKET_DIR / "pit" / "ohlcv_1d"
EVIDENCE_DIR = ROOT / "evidence"
STATE_DIR = ROOT / "data" / "state"

API_PREFIX = "/api/v1"
MAX_CANDLES = 2_000
DEFAULT_CANDLES = 365
CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=300"

CORS_ORIGINS: tuple[str, ...] = tuple(
    origin.strip()
    for origin in os.environ.get("CRYPTO_ANALYZER_CORS_ORIGINS", "").split(",")
    if origin.strip()
)


def public_file(name: str) -> Path:
    """Arquivo publicado pelo pipeline em `frontend/public`."""
    return PUBLIC_DIR / name


def pit_file(symbol: str) -> Path:
    """Série point-in-time de um par, ex.: `BTC/USDT` -> symbol=BTC_USDT."""
    safe = symbol.replace("/", "_")
    if not safe.replace("_", "").isalnum():
        raise ValueError("símbolo inválido")
    return PIT_DIR / f"symbol={safe}" / "data.parquet"
