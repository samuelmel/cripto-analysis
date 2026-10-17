"""Contrato entre o frontend e o pipeline: todo campo que um tipo de `signals.ts` declara existe no schema Python que gera
o arquivo, e todo campo que o leitor (`loadSignals.ts`) consome está no tipo. Garante que o painel nunca lê uma coluna que o
backend não publica (CLAUDE.md §2: o tipo espelha o schema). Sem rede, sem Node."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.loaders.positions_store import POSITIONS_SCHEMA
from src.loaders.source_log import SOURCE_LOG_SCHEMA
from src.transformers.anomaly_detector import HISTORY_SCHEMA
from src.transformers.forecast import FORECAST_SCHEMA
from src.transformers.position_advisor import CLOSED_SCHEMA, POSITION_SCHEMA
from src.transformers.recommendation import RECOMMENDATION_SCHEMA, SIGNALS_SCHEMA
from src.transformers.position_log import POSITION_STATE_LOG_SCHEMA
from src.transformers.regimes import REGIME_SCHEMA
from src.transformers.selection_backtest import SELECTION_PERF_SCHEMA
from src.transformers.signal_validation import EVIDENCE_SCHEMA
from src.transformers.trade_simulator import PERFORMANCE_SCHEMA, TRADE_SCHEMA

ROOT = Path(__file__).resolve().parent.parent
TYPES = (ROOT / "frontend" / "src" / "types" / "signals.ts").read_text(encoding="utf-8")
LOADER = (ROOT / "frontend" / "src" / "data" / "loadSignals.ts").read_text(encoding="utf-8")

# interface do TypeScript -> (schema Python, função do leitor)
CONTRACTS: dict[str, tuple[dict[str, str], str]] = {
    "DailySignal": (SIGNALS_SCHEMA, "parseSignal"),
    "Recommendation": (RECOMMENDATION_SCHEMA, "parseRecommendation"),
    "SelectionPerf": (SELECTION_PERF_SCHEMA, "parseSelectionPerf"),
    "HistoryPoint": (HISTORY_SCHEMA, "parseHistory"),
    "Trade": (TRADE_SCHEMA, "parseTrade"),
    "Performance": (PERFORMANCE_SCHEMA, "parsePerformance"),
    "Forecast": (FORECAST_SCHEMA, "parseForecast"),
    "SourceEvent": (SOURCE_LOG_SCHEMA, "parseSource"),
    "Position": (POSITION_SCHEMA, "parsePosition"),
    "ClosedPosition": (CLOSED_SCHEMA, "parseClosed"),
    "MarketRegime": (REGIME_SCHEMA, "parseMarketRegime"),
    "SignalEvidence": (EVIDENCE_SCHEMA, "parseEvidence"),
    "PositionStateRow": (POSITION_STATE_LOG_SCHEMA, "parsePositionState"),
}


def interface_fields(name: str) -> list[str]:
    match = re.search(rf"export interface {name} \{{(.*?)\n\}}", TYPES, re.S)
    assert match, f"interface {name} não encontrada em signals.ts"
    return re.findall(r"readonly (\w+)\??:", match.group(1))


def parser_keys(name: str) -> list[str]:
    match = re.search(rf"const {name} = .*?\n\}}\);", LOADER, re.S)
    assert match, f"{name} não encontrada em loadSignals.ts"
    return re.findall(r'\br, "(\w+)"', match.group(0))


@pytest.mark.parametrize("interface", list(CONTRACTS))
def test_every_typescript_field_is_published_by_the_python_schema(interface: str) -> None:
    schema, _ = CONTRACTS[interface]
    missing = [f for f in interface_fields(interface) if f not in schema]
    assert not missing, f"{interface}: campos que o backend não publica: {missing}"


@pytest.mark.parametrize("interface", list(CONTRACTS))
def test_the_loader_reads_only_declared_fields_and_every_declared_field(interface: str) -> None:
    _, parser = CONTRACTS[interface]
    declared, read = interface_fields(interface), parser_keys(parser)
    assert set(read) <= set(declared), f"{parser} lê campos fora do tipo: {sorted(set(read) - set(declared))}"
    assert set(declared) <= set(read), f"{parser} não lê campos do tipo: {sorted(set(declared) - set(read))}"


def test_the_dashboard_loads_every_published_file_and_only_regimes_are_new() -> None:
    for name in ("daily_signals", "recommendation", "selection_backtest", "market_regimes", "history", "backtest",
                 "performance", "forecast", "sources", "strategy_lab", "positions", "closed_positions"):
        assert f"/{name}.parquet" in LOADER, name
    assert "optionalRows(`${base}/market_regimes.parquet`)" in LOADER  # opcional: o painel abre sem ele
