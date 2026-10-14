"""Servidor MCP (stdio) que expõe o pipeline diário como a tool `run_crypto_pipeline`.

Só orquestra: executa `python -m src.pipeline` em subprocesso e devolve o resultado.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT = PROJECT_DIR / "frontend" / "public" / "daily_signals.parquet"
TIMEOUT_S = 1800
TAIL_LINES = 40

mcp = MCPServer("crypto-analyzer")


@mcp.tool()
def run_crypto_pipeline() -> str:
    """Executa a extração diária e o ETL completo, gravando frontend/public/daily_signals.parquet."""
    proc = subprocess.run(
        [sys.executable, "-m", "src.pipeline"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_S,
    )
    log = "\n".join((proc.stdout + proc.stderr).splitlines()[-TAIL_LINES:])
    if proc.returncode != 0:
        raise RuntimeError(f"Pipeline falhou (exit {proc.returncode}):\n{log}")
    return f"Pipeline concluído. Saída: {OUTPUT}\n{log}"


if __name__ == "__main__":
    mcp.run()
