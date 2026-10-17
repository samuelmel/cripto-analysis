"""Linha de base de regressão (Fase 0): o pipeline completo sobre um mercado sintético fixo.

Congela as saídas do commit de referência para que qualquer refatoração que deveria ser puramente técnica possa
ser comparada com o comportamento anterior. Uma diferença aqui significa que a regra mudou: ou a mudança é um erro,
ou é intencional e precisa ser documentada (docs/QUANT_ROADMAP_PROGRESS.md) antes de regenerar a referência com

    UPDATE_GOLDEN=1 uv run pytest tests/test_golden_baseline.py

Os números são de um mercado SINTÉTICO e não dizem nada sobre o mercado real.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from src import pipeline
from src.loaders.market_store import write_fng, write_ohlcv
from tests.synthetic_market import RUN_TS, synthetic_candles, synthetic_fng

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"
RTOL = 1e-7


def _scalar_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Só as colunas escalares (listas de texto ficam de fora: são explicação, não número)."""
    return df[[c for c in df.columns if df[c].dtype != "object"]].reset_index(drop=True)


def _history_digest(history: pd.DataFrame) -> pd.DataFrame:
    """Resumo por moeda do histórico de indicadores (o arquivo inteiro é grande demais para versionar)."""
    g = history.groupby("symbol", observed=True)
    out = pd.DataFrame(
        {
            "rows": g.size(),
            "first_ts": g["timestamp"].min(),
            "last_ts": g["timestamp"].max(),
            **{f"sum_{c}": g[c].sum() for c in ("close", "sma_90", "zscore_90", "sma_200", "rsi_14")},
            "uptrend_days": g["uptrend"].sum(),
            "panic_days": g["panic"].sum(),
            "buy_days": g["stage"].apply(lambda s: int(s.eq("COMPRAR").sum())),
            "watch_days": g["stage"].apply(lambda s: int(s.eq("PREPARAR").sum())),
        }
    )
    return out.reset_index().astype({"symbol": "string"})


@pytest.fixture(scope="module")
def outputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, pd.DataFrame]:
    workdir = tmp_path_factory.mktemp("golden")
    cwd = Path.cwd()
    os.chdir(workdir)
    try:
        candles = synthetic_candles()
        write_ohlcv(candles)
        write_fng(synthetic_fng(candles))
        result = pipeline.analyze(RUN_TS)
        history = pd.read_parquet(workdir / "frontend" / "public" / "history.parquet")
    finally:
        os.chdir(cwd)
    return {
        "performance": result["performance"].reset_index(drop=True),
        "selection_backtest": result["selection_backtest"].reset_index(drop=True),
        "backtest": result["backtest"].reset_index(drop=True),
        "forecast": result["forecast"].reset_index(drop=True),
        "daily_signals": _scalar_columns(result["signals"]),
        "recommendation": _scalar_columns(result["recommendation"]),
        "history_digest": _history_digest(history),
    }


@pytest.mark.parametrize(
    "name",
    ["performance", "selection_backtest", "backtest", "forecast", "daily_signals", "recommendation", "history_digest"],
)
def test_output_matches_golden(outputs: dict[str, pd.DataFrame], name: str) -> None:
    path = GOLDEN_DIR / f"{name}.parquet"
    current = outputs[name]
    if UPDATE:
        GOLDEN_DIR.mkdir(exist_ok=True)
        current.to_parquet(path, index=False, compression="zstd")
    assert path.is_file(), f"referência ausente: {path} (gere com UPDATE_GOLDEN=1)"
    golden = pd.read_parquet(path)
    pd.testing.assert_frame_equal(current, golden, check_dtype=False, rtol=RTOL)


def test_synthetic_baseline_is_not_empty(outputs: dict[str, pd.DataFrame]) -> None:
    """A base sintética exercita as regras: há operações de tendência e todas as estratégias de seleção."""
    assert len(outputs["backtest"]) >= 5
    assert outputs["selection_backtest"]["strategy"].nunique() == 6
    assert outputs["performance"]["total_return_pct"].notna().any()
    assert outputs["history_digest"]["panic_days"].sum() > 0  # o alerta de pânico (informativo) é exercitado
