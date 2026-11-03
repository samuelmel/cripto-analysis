"""Pasta de estado persistente (`data/state/`): checkout local da branch `state` do repositório.

Guarda o que precisa sobreviver entre execuções e ficar acessível ao GitHub Actions (CLAUDE.md §3: tudo em Parquet):

    positions.parquet           suas posições (compras e vendas)
    signal_log.parquet          registro imutável de sinais, uma linha por moeda e dia, com cadeia de hash
    position_states.parquet     histórico diário do estado de cada posição aberta
    notifications.parquet       avisos de mudança de estado já enviados ao Telegram
    model_predictions.parquet   previsões diárias dos modelos de IA em modo sombra, com cadeia de hash (append-only)
    sim_decisions.parquet       decisões das carteiras simuladas em reais (dinheiro fictício), com cadeia de hash (append-only)
    fng_history.parquet         cópia do histórico do Fear & Greed visto em cada execução (append-only, com revisões)

A sincronização com a branch (git) fica em `src/state_sync.py`. Esta pasta é ignorada pelo git da branch `main`.
"""

from __future__ import annotations

from pathlib import Path

STATE_DIR = Path("data/state")


def positions_path(base: Path = STATE_DIR) -> Path:
    return base / "positions.parquet"


def signal_log_path(base: Path = STATE_DIR) -> Path:
    return base / "signal_log.parquet"


def position_states_path(base: Path = STATE_DIR) -> Path:
    return base / "position_states.parquet"


def notifications_path(base: Path = STATE_DIR) -> Path:
    return base / "notifications.parquet"


def model_predictions_path(base: Path = STATE_DIR) -> Path:
    return base / "model_predictions.parquet"


def fng_history_path(base: Path = STATE_DIR) -> Path:
    return base / "fng_history.parquet"


def sim_decisions_path(base: Path = STATE_DIR) -> Path:
    return base / "sim_decisions.parquet"
