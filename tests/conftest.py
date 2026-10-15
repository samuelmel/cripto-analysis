"""Fixtures comuns: bloqueio de rede (nenhum teste faz chamada real) e raiz do projeto no sys.path."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("teste tentou acessar a rede")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
