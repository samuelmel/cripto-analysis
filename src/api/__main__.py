"""Entrypoint da API. Host/porta vêm do ambiente ou dos argumentos do processo."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("CRYPTO_ANALYZER_API_HOST", "127.0.0.1")
    port = int(os.environ.get("CRYPTO_ANALYZER_API_PORT", "8000"))
    reload = os.environ.get("CRYPTO_ANALYZER_API_RELOAD", "0") == "1"
    uvicorn.run("src.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
