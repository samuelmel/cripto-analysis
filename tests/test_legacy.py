"""Scripts legados da raiz: não contradizem a regra atual (pânico = alerta informativo) nem gravam CSV."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import feature_engineering
import signal_analyzer


def _crash_then_flat() -> pd.DataFrame:
    """Um ativo com 4 anos de alta lenta e uma queda brusca no fim: z-score e RSI em pânico na última vela."""
    days = pd.date_range(end=pd.Timestamp("2026-06-30", tz="UTC"), periods=4 * 365, freq="D")
    close = np.linspace(100.0, 200.0, len(days))
    close[-10:] = np.linspace(200.0, 90.0, 10)
    return pd.DataFrame(
        {"exchange": "binance", "timeframe": "1d", "symbol": "AAA_USDT", "timestamp": days, "close": close}
    )


def test_panic_alert_is_informative_not_a_buy_recommendation() -> None:
    alerts = signal_analyzer.find_panic_alerts(_crash_then_flat())
    assert alerts["symbol"].tolist() == ["AAA/USDT"]
    assert "Grau de Confiança" not in alerts.columns
    assert signal_analyzer.CONF_COL in alerts.columns
    doc = signal_analyzer.__doc__ or ""
    assert "NÃO é recomendação de compra" in doc
    assert not hasattr(signal_analyzer, "find_signals")


def test_signal_analyzer_refuses_csv_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["signal_analyzer.py", "--data", str(tmp_path), "--out", str(tmp_path / "x.csv")])
    with pytest.raises(SystemExit, match="parquet"):
        signal_analyzer.main()
    assert not (tmp_path / "x.csv").exists()


def test_feature_engineering_refuses_csv_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["feature_engineering.py", "--input", str(tmp_path), "--output", str(tmp_path / "f.csv")])
    assert feature_engineering.main() == 1
    assert not (tmp_path / "f.csv").exists()
