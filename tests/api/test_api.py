"""Contratos da API somente leitura, exercitados contra os Parquets publicados."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.settings import PUBLIC_DIR

pytestmark = pytest.mark.skipif(
    not (PUBLIC_DIR / "daily_signals.parquet").is_file(),
    reason="Parquets publicados ausentes; testes de integração só rodam após o pipeline",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_overview_is_internally_consistent(client: TestClient) -> None:
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["budget_brl"] == 100.0
    assert len(body["signals"]) == 32
    assert body["recommendation"]["total_brl"] <= body["recommendation"]["budget_brl"]
    assert any(signal["selected"] for signal in body["signals"])
    assert body["system"]["data_day"] is not None


def test_signals_share_the_same_run(client: TestClient) -> None:
    body = client.get("/api/v1/signals").json()
    run_ts = body["run_ts"]
    assert all(signal["run_ts"] == run_ts for signal in body["signals"])
    assert body["recommendation"]["run_ts"] == run_ts


def test_market_has_btc_history_and_ranked_assets(client: TestClient) -> None:
    body = client.get("/api/v1/market").json()
    assert body["brief"]["regime"] in {"FAVORAVEL", "NEUTRO", "DEFENSIVO", "INDISPONIVEL"}
    assert len(body["assets"]) == 32
    assert len(body["btc_candles"]) > 300
    assert len(body["regime_history"]) > 300


def test_assets_search_and_detail(client: TestClient) -> None:
    search = client.get("/api/v1/assets", params={"q": "btc"}).json()
    assert [row["symbol"] for row in search] == ["BTC/USDT"]
    detail = client.get("/api/v1/assets/BTC", params={"days": 30}).json()
    assert detail["symbol"] == "BTC/USDT"
    assert len(detail["candles"]) == 30
    assert detail["rows"] > 3_000
    assert detail["analysis"]["symbol"] == "BTC/USDT"


def test_unknown_asset_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/assets/NAOEXISTE").status_code == 404


def test_research_catalog_and_evidence(client: TestClient) -> None:
    body = client.get("/api/v1/research").json()
    assert len(body["studies"]) >= 10
    assert body["evidence"]["total"] == 683
    assert body["evidence"]["validated"] == 0
    assert len(body["entry_levels"]) == 12
    assert any(row["level"] == "PROMISSOR" for row in body["entry_levels"])
    assert client.get("/api/v1/research/sma200-risk").json()["status"] == "validado"
    assert client.get("/api/v1/research/nao-existe").status_code == 404


def test_portfolios_do_not_invent_values(client: TestClient) -> None:
    body = client.get("/api/v1/portfolios").json()
    ids = [row["id"] for row in body["portfolios"]]
    assert ids == ["PAINEL", "IA", "REVERSAO", "SO_BTC", "DCA"]
    assert body["data_available"] is False
    dca = client.get("/api/v1/portfolios/DCA").json()
    assert dca["portfolio"]["status"] == "reference"
    assert {metric["period"] for metric in dca["metrics"]} == {"TREINO", "VALIDACAO", "TESTE"}
    painel = client.get("/api/v1/portfolios/PAINEL").json()
    assert painel["portfolio"]["status"] == "unavailable"
    assert painel["positions"] == []


def test_system_status_lists_artifacts_and_read_only_state(client: TestClient) -> None:
    body = client.get("/api/v1/system/status").json()
    assert body["api_version"] == "v1"
    assert body["state_branch"].startswith("state é somente leitura")
    assert any(item["name"] == "Sinais diários" and item["status"] == "ok" for item in body["artifacts"])


def test_api_has_no_write_routes() -> None:
    methods = {method for route in app.routes for method in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}
