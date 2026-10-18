"""Avisos só na mudança: candidata dispara ou se desfaz; ATENÇÃO sugere reduzir o tamanho da posição."""

from __future__ import annotations

import pandas as pd

from src.transformers.entry_live import CHANGE_FIRED, CHANGE_SCHEMA, CHANGE_UNDONE
from src.transformers.notification import (
    WATCH_SUGGESTION,
    WATCHLIST_DISCLAIMER,
    format_entry_changes,
    format_position_changes,
    validate_messages,
)

NOW = pd.Timestamp("2026-10-18 00:10", tz="UTC")


def _changes(*rows: tuple[str, str, str, str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(CHANGE_SCHEMA)).astype(CHANGE_SCHEMA)


def _signals(**stages: str) -> pd.DataFrame:
    return pd.DataFrame({"symbol": [f"{k}/USDT" for k in stages], "stage": list(stages.values())})


def test_sem_mudanca_sem_mensagem() -> None:
    assert format_entry_changes(None, _signals(BTC="NEUTRO"), now=NOW) == []
    assert format_entry_changes(_changes(), _signals(BTC="NEUTRO"), now=NOW) == []


def test_disparou_e_desfez() -> None:
    ch = _changes(("NEAR/USDT", "E", "PROMISSOR", CHANGE_FIRED), ("SOL/USDT", "E", "PROMISSOR", CHANGE_UNDONE),
                  ("ETH/USDT", "C", "VALIDADO", CHANGE_FIRED))
    texts = format_entry_changes(ch, _signals(NEAR="NEUTRO", SOL="NEUTRO", ETH="COMPRAR"), now=NOW)
    assert validate_messages(texts) == []
    text = "\n".join(texts)
    assert "- NEAR disparou: E (entre as 5 maiores notas do score de seleção), PROMISSOR → em observação." in text
    assert "- ETH disparou: C (rompimento da máxima de 55 dias com volume), VALIDADO → COMPRAR." in text
    assert "- SOL se desfez: saiu de E" in text
    assert WATCHLIST_DISCLAIMER in text


def test_moeda_sem_dado_nao_gera_aviso() -> None:
    ch = _changes(("SOL/USDT", "E", "PROMISSOR", CHANGE_UNDONE))
    assert format_entry_changes(ch, _signals(SOL="INDISPONÍVEL"), now=NOW) == []


def _position_change(state: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol": "BTC/USDT", "prev_state": "SEGURAR", "state": state, "rule": "STOP", "detail": "a 10% do stop",
        "return_pct": -10.0, "drawdown_entry_pct": -12.0, "drawdown_peak_pct": -15.0, "rule_evidence": None,
    }])


def test_atencao_sugere_reduzir_o_tamanho() -> None:
    text = "\n".join(format_position_changes(_position_change("ATENÇÃO"), now=NOW))
    assert WATCH_SUGGESTION in text
    assert WATCH_SUGGESTION not in "\n".join(format_position_changes(_position_change("VENDER"), now=NOW))
