"""API FastAPI somente leitura para o painel. Execute com `uv run python -m src.api`."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter

from .domain import base_of, name_of, ranked_assets
from .readers import MissingArtifactError, optional_records
from .research_catalog import STUDIES, study_by_id
from .schemas import (
    AssetDetail,
    AssetSummary,
    EntryLevelRow,
    EvidenceSummary,
    MarketResponse,
    OverviewResponse,
    PortfolioDetail,
    PortfolioListResponse,
    ResearchResponse,
    ResearchStudy,
    SignalEvidence,
    SignalsResponse,
    SystemStatus,
)
from .service import (
    API_VERSION,
    InconsistentRunError,
    asset_detail,
    load_lab,
    load_recommendation,
    load_signals,
    market_response,
    now_utc,
    overview,
    portfolio_detail,
    portfolios,
    signals_response,
    system_status,
)
from .settings import API_PREFIX, CORS_ORIGINS, FRONTEND_DIST, public_file

router = APIRouter(prefix=API_PREFIX)


@router.get("/overview", response_model=OverviewResponse)
def get_overview() -> OverviewResponse:
    return overview()


@router.get("/signals", response_model=SignalsResponse)
def get_signals() -> SignalsResponse:
    return signals_response()


@router.get("/market", response_model=MarketResponse)
def get_market() -> MarketResponse:
    return market_response()


@router.get("/assets", response_model=list[AssetSummary])
def get_assets(q: str = Query(default="", max_length=40)) -> list[AssetSummary]:
    rows = ranked_assets(load_signals())
    needle = q.strip().lower()
    if not needle:
        return rows
    return [row for row in rows if needle in row.symbol.lower() or needle in row.name.lower()]


@router.get("/assets/{symbol}", response_model=AssetDetail)
def get_asset(symbol: str, days: int = Query(default=365, ge=30, le=2000)) -> AssetDetail:
    try:
        return asset_detail(symbol, days)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Série point-in-time não encontrada para {symbol}.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/research", response_model=ResearchResponse)
def get_research() -> ResearchResponse:
    evidence = [SignalEvidence.model_validate(row) for row in optional_records(public_file("signal_evidence.parquet"))]
    entry_levels = [
        EntryLevelRow.model_validate(row)
        for row in optional_records(public_file("entry_signal_levels.parquet"))
    ]
    validated = [row.symbol for row in evidence if row.status == "VALIDADA"]
    summary = EvidenceSummary(
        total=len(evidence),
        validated=sum(1 for row in evidence if row.status == "VALIDADA"),
        not_validated=sum(1 for row in evidence if row.status == "NAO_VALIDADA"),
        no_evidence=sum(1 for row in evidence if row.status == "SEM_EVIDENCIA"),
        revoked=sum(1 for row in evidence if row.status == "REVOGADA"),
        not_evaluated=sum(1 for row in evidence if row.status == "NAO_AVALIADA"),
        validated_symbols=validated,
    )
    return ResearchResponse(
        studies=list(STUDIES),
        lab=load_lab(),
        entry_levels=entry_levels,
        evidence=summary,
        generated_at=now_utc(),
    )


@router.get("/research/{study_id}", response_model=ResearchStudy)
def get_study(study_id: str) -> ResearchStudy:
    study = study_by_id(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Estudo não encontrado.")
    return study


@router.get("/portfolios", response_model=PortfolioListResponse)
def get_portfolios() -> PortfolioListResponse:
    return portfolios()


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioDetail)
def get_portfolio(portfolio_id: str) -> PortfolioDetail:
    try:
        return portfolio_detail(portfolio_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Carteira não encontrada.") from exc


@router.get("/system/status", response_model=SystemStatus)
def get_system_status() -> SystemStatus:
    return system_status(load_recommendation())


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": API_VERSION}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Crypto Analyzer API",
        version=API_VERSION,
        description="Leitura dos artefatos Parquet publicados pelo pipeline. Nenhum endpoint escreve ou envia ordens.",
    )
    if CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(CORS_ORIGINS),
            allow_methods=["GET"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    app.include_router(router)

    @app.exception_handler(MissingArtifactError)
    async def missing_artifact(_request: object, exc: MissingArtifactError) -> FileResponse:
        raise HTTPException(status_code=503, detail=f"Artefato indisponível: {exc}") from exc

    @app.exception_handler(InconsistentRunError)
    async def inconsistent_run(_request: object, exc: InconsistentRunError) -> FileResponse:
        raise HTTPException(status_code=503, detail=f"Execução inconsistente: {exc}") from exc

    if (FRONTEND_DIST / "index.html").is_file():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:

        @app.get("/")
        def root() -> dict[str, str]:
            return {"name": "Crypto Analyzer API", "docs": "/docs", "api": API_PREFIX}

    return app


app = create_app()
