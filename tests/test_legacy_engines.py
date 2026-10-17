"""Motores LEGADOS (anteriores à Fase 2): continuam reproduzindo exatamente os resultados antigos.

Os arquivos em `tests/golden/legacy_v1/` foram gerados pelo código original (commit abcccd6) sobre o mercado
sintético. As funções legadas (`trade_simulator.performance_summary`/`run_portfolio`/`backtest` e
`selection_backtest.evaluate_selection_legacy`/`run_weighted`) existem só para isto: qualquer resultado produzido
com as premissas antigas continua reproduzível e identificável como antigo. Resultado novo usa o motor único.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.config import BUDGET_BRL, FEE_PER_SIDE, RECOMMENDED, SELECTION_REBALANCE_DAYS, UNIVERSE
from src.pipeline import PERIODS, SELECTION_PERIODS
from src.transformers.anomaly_detector import classify_history
from src.transformers.data_quality import clean_candles
from src.transformers.selection import compute_features, regime_series
from src.transformers.selection_backtest import evaluate_selection_legacy
from src.transformers.strategies import market_from_candles
from src.transformers.trade_simulator import backtest, performance_summary
from src.transformers.universe import select_universe
from tests.synthetic_market import synthetic_candles, synthetic_fng
from tests.test_golden_baseline import GOLDEN_DIR, RTOL

LEGACY = GOLDEN_DIR / "legacy_v1"


@pytest.fixture(scope="module")
def legacy() -> dict[str, pd.DataFrame]:
    raw = synthetic_candles()
    kept = select_universe(UNIVERSE, raw).kept
    candles = clean_candles(raw[raw["symbol"].isin(kept)])
    history = classify_history(candles, synthetic_fng(raw))
    features = compute_features(market_from_candles(candles))
    perf, _ = evaluate_selection_legacy(features, regime_series(features), SELECTION_PERIODS, BUDGET_BRL, SELECTION_REBALANCE_DAYS)
    return {
        "performance": performance_summary(history, {"PRINCIPAIS": RECOMMENDED, "TODAS": kept}, PERIODS, FEE_PER_SIDE),
        "selection_backtest": perf,
        "backtest": backtest(history, RECOMMENDED),
    }


@pytest.mark.parametrize("name", ["performance", "selection_backtest", "backtest"])
def test_legacy_engines_reproduce_the_pre_phase2_results(legacy: dict[str, pd.DataFrame], name: str) -> None:
    golden = pd.read_parquet(LEGACY / f"{name}.parquet")
    pd.testing.assert_frame_equal(legacy[name].reset_index(drop=True), golden, check_dtype=False, rtol=RTOL)
