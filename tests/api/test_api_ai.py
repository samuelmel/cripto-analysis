"""Estado da IA (trava de promoção) exposto pela API de carteiras."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.api import service
from src.loaders.parquet_loader import write_parquet
from src.transformers.model_shadow import ai_status_table, promotion_gate


def test_ai_status_is_read_from_the_published_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = pd.DataFrame(columns=["model", "day", "symbol", "in_top_k", "forward_30", "universe_30"])
    write_parquet(ai_status_table(promotion_gate(pd.DataFrame(), empty), ["NEAR/USDT"]), tmp_path / "ai_status.parquet")
    monkeypatch.setattr(service, "public_file", lambda name: tmp_path / name)
    ai = service._ai_status()
    assert ai is not None
    assert ai.status == "DADOS_INSUFICIENTES" and ai.approved is False
    assert ai.picks == "NEAR" and ai.n_days == 0 and ai.min_days == 90
    assert "IA (em teste)" in ai.message and ai.mean_excess_pp is None


def test_ai_status_is_none_when_the_file_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "public_file", lambda name: tmp_path / name)
    assert service._ai_status() is None
