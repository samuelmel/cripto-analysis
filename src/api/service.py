"""Orquestração de leitura da API. Sem regras de investimento e sem escrita."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .domain import (
    base_of,
    latest_regime,
    market_brief,
    name_of,
    ranked_assets,
)
from .readers import frame, latest_date, optional_records, records, to_records
from .schemas import (
    ArtifactStatus,
    AssetDetail,
    Candle,
    DailySignal,
    Forecast,
    LabResult,
    MarketRegime,
    MarketResponse,
    OverviewResponse,
    Performance,
    PortfolioDetail,
    PortfolioListResponse,
    PortfolioMetric,
    PortfolioSummary,
    Recommendation,
    SelectionPerformance,
    SignalsResponse,
    SimPosition,
    SimWalletPositionRow,
    SimWalletSummaryRow,
    SourceEvent,
    SystemStatus,
)
from .settings import DEFAULT_CANDLES, MAX_CANDLES, ROOT, STATE_DIR, public_file, pit_file

API_VERSION = "v1"


class InconsistentRunError(RuntimeError):
    """Os arquivos publicados não fecham entre si."""


def now_utc() -> datetime:
    return datetime.now(UTC)


def load_signals() -> list[DailySignal]:
    return [DailySignal.model_validate(row) for row in records(public_file("daily_signals.parquet"))]


def load_recommendation() -> Recommendation:
    rows = records(public_file("recommendation.parquet"))
    if len(rows) != 1:
        raise InconsistentRunError("recommendation.parquet deveria ter uma linha")
    return Recommendation.model_validate(rows[0])


def validate_run(signals: list[DailySignal], recommendation: Recommendation) -> None:
    problems: list[str] = []
    total = sum(signal.allocation_brl for signal in signals)
    if any(signal.run_ts != recommendation.run_ts for signal in signals):
        problems.append("daily_signals e recommendation são de execuções diferentes")
    if any(signal.allocation_brl < 0 for signal in signals):
        problems.append("aporte negativo")
    if total > recommendation.budget_brl + 0.005:
        problems.append("soma dos aportes acima do orçamento")
    if abs(total - recommendation.total_brl) > 0.005:
        problems.append("total do resumo diferente da soma por moeda")
    if any(signal.allocation_brl > 0 and not signal.selected for signal in signals):
        problems.append("aporte em moeda não selecionada")
    if problems:
        raise InconsistentRunError("; ".join(problems))


def load_performance() -> list[Performance]:
    return [Performance.model_validate(row) for row in records(public_file("performance.parquet"))]


def load_selection_performance() -> list[SelectionPerformance]:
    return [
        SelectionPerformance.model_validate(row)
        for row in optional_records(public_file("selection_backtest.parquet"))
    ]


def load_forecasts() -> list[Forecast]:
    return [Forecast.model_validate(row) for row in optional_records(public_file("forecast.parquet"))]


def load_regimes() -> list[MarketRegime]:
    return [MarketRegime.model_validate(row) for row in optional_records(public_file("market_regimes.parquet"))]


def load_sources() -> list[SourceEvent]:
    return [SourceEvent.model_validate(row) for row in optional_records(public_file("sources.parquet"))]


def load_lab() -> list[LabResult]:
    return [LabResult.model_validate(row) for row in optional_records(public_file("strategy_lab.parquet"))]


def _artifact(name: str, path: Path, last_column: str | None = None) -> ArtifactStatus:
    if not path.is_file():
        return ArtifactStatus(name=name, path=str(path.relative_to(ROOT)), status="missing")
    data = frame(path)
    updated = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    last = latest_date(data, last_column) if last_column is not None else None
    last_dt = datetime.fromisoformat(last + "T00:00:00+00:00") if last is not None else None
    return ArtifactStatus(
        name=name,
        path=str(path.relative_to(ROOT)),
        status="ok",
        rows=len(data),
        updated_at=updated,
        last_data_ts=last_dt,
    )


def system_status(recommendation: Recommendation) -> SystemStatus:
    sources = load_sources()
    artifacts = [
        _artifact("Sinais diários", public_file("daily_signals.parquet"), "timestamp"),
        _artifact("Recomendação", public_file("recommendation.parquet"), "data_day"),
        _artifact("Desempenho", public_file("performance.parquet")),
        _artifact("Backtest da seleção", public_file("selection_backtest.parquet")),
        _artifact("Regimes de mercado", public_file("market_regimes.parquet"), "timestamp"),
        _artifact("Previsão", public_file("forecast.parquet"), "asof"),
        _artifact("Fontes", public_file("sources.parquet"), "last_data_ts"),
        _artifact("Laboratório", public_file("strategy_lab.parquet")),
        _artifact("Evidência por moeda", public_file("signal_evidence.parquet")),
        _artifact("Carteiras simuladas", public_file("sim_wallets.parquet"), "as_of"),
        _artifact("Posições simuladas", public_file("sim_wallet_positions.parquet")),
        _artifact("Posições", public_file("positions.parquet")),
        _artifact("Posições encerradas", public_file("closed_positions.parquet")),
    ]
    errors = sum(1 for source in sources if source.status == "erro")
    data_day = recommendation.data_day
    lag = (now_utc().date() - data_day.date()).days if data_day is not None else None
    missing_core = any(
        artifact.status == "missing"
        for artifact in artifacts
        if artifact.name in {"Sinais diários", "Recomendação", "Desempenho"}
    )
    stale = lag is not None and lag > 1
    status: Literal["ok", "partial", "unavailable"] = (
        "unavailable" if missing_core else "partial" if stale or errors > 0 else "ok"
    )
    notes: list[str] = []
    if data_day is not None and lag is not None and lag > 1:
        notes.append(f"Dados de {data_day.date().isoformat()}; defasagem de {lag} dias em relação a hoje.")
    if errors:
        notes.append(f"{errors} fonte(s) com erro na última coleta.")
    if any(artifact.name == "Carteiras simuladas" and artifact.status == "missing" for artifact in artifacts):
        notes.append("Carteiras simuladas ainda não publicadas; a página mostra o estado indisponível.")
    if not notes:
        notes.append("Artefatos principais presentes e coerentes.")
    return SystemStatus(
        status=status,
        generated_at=now_utc(),
        last_run=recommendation.run_ts,
        data_day=recommendation.data_day,
        source_health=sources,
        artifacts=artifacts,
        state_branch="state é somente leitura para esta aplicação; nenhuma decisão é gravada pela API.",
        note=" ".join(notes),
    )


def overview() -> OverviewResponse:
    signals = load_signals()
    recommendation = load_recommendation()
    validate_run(signals, recommendation)
    return OverviewResponse(
        recommendation=recommendation,
        signals=signals,
        performance=load_performance(),
        selection_performance=load_selection_performance(),
        forecast=load_forecasts(),
        market=latest_regime(load_regimes()),
        system=system_status(recommendation),
        generated_at=now_utc(),
    )


def signals_response() -> SignalsResponse:
    signals = load_signals()
    recommendation = load_recommendation()
    validate_run(signals, recommendation)
    return SignalsResponse(run_ts=recommendation.run_ts, recommendation=recommendation, signals=signals)


@dataclass(frozen=True)
class PitSeries:
    candles: list[Candle]
    source: str
    first_date: datetime | None
    last_date: datetime | None
    rows: int


def pit_series(symbol: str, days: int = DEFAULT_CANDLES) -> PitSeries:
    path = pit_file(symbol)
    if not path.is_file():
        raise FileNotFoundError(path.name)
    full = frame(path).sort_values("timestamp")
    data = full.tail(days)
    candles = [Candle.model_validate(row) for row in to_records(data)]
    first = full["timestamp"].iloc[0].to_pydatetime() if len(full) else None
    last = full["timestamp"].iloc[-1].to_pydatetime() if len(full) else None
    source = str(full["source"].iloc[-1]) if "source" in full and len(full) else "binance"
    return PitSeries(candles=candles, source=source, first_date=first, last_date=last, rows=len(full))


def asset_detail(symbol: str, days: int = DEFAULT_CANDLES) -> AssetDetail:
    pair = symbol if "/" in symbol else f"{symbol.upper()}/USDT"
    series = pit_series(pair, max(30, min(days, MAX_CANDLES)))
    analysis = next((signal for signal in load_signals() if signal.symbol == pair), None)
    return AssetDetail(
        symbol=pair,
        base=base_of(pair),
        name=name_of(pair),
        source=series.source,
        first_date=series.first_date,
        last_date=series.last_date,
        rows=series.rows,
        candles=series.candles,
        analysis=analysis,
        eligibility_note=(
            "A série é point-in-time: cada dia usa apenas candles existentes até aquele dia. "
            "A elegibilidade histórica do universo não é recalculada pela API."
        ),
        universe_note=(
            "A análise de hoje cobre as 32 moedas do universo configurado. "
            "O histórico point-in-time contém 683 pares e é usado somente para leitura de preços."
        ),
    )


def market_response() -> MarketResponse:
    signals = load_signals()
    recommendation = load_recommendation()
    validate_run(signals, recommendation)
    regimes = load_regimes()
    series = pit_series("BTC/USDT", DEFAULT_CANDLES)
    return MarketResponse(
        brief=market_brief(signals, recommendation, latest_regime(regimes)),
        assets=ranked_assets(signals),
        btc_candles=series.candles,
        regime_history=regimes[-365:],
        forecasts=load_forecasts(),
        sources=load_sources(),
        generated_at=now_utc(),
    )


_WALLET_RULES: dict[str, str] = {
    "PAINEL": "Segue a recomendação diária e vende pelas regras de saída do painel.",
    "IA": "Modelo em modo sombra; compra as 5 maiores probabilidades em lotes de 30 dias.",
    "REVERSAO": "Estratégia experimental sem estudo: compra as 5 piores de 90 dias quando o BTC está acima da SMA 200.",
    "SO_BTC": "Compra R$ 1.000 de BTC no primeiro dia e nunca vende. Referência.",
}


def _sim_summaries() -> list[SimWalletSummaryRow]:
    return [
        SimWalletSummaryRow.model_validate(row)
        for row in optional_records(public_file("sim_wallets.parquet"))
    ]


def _catalog() -> list[PortfolioSummary]:
    available = {row.wallet: row for row in _sim_summaries()}
    catalog: list[PortfolioSummary] = []
    for wallet in ("PAINEL", "IA", "REVERSAO", "SO_BTC"):
        row = available.get(wallet)
        if row is None:
            catalog.append(
                PortfolioSummary(
                    id=wallet,
                    name=wallet.replace("_", " "),
                    kind="simulated",
                    status="unavailable",
                    rule=_WALLET_RULES[wallet],
                    experimental=wallet in {"IA", "REVERSAO"},
                    initial_brl=1000.0,
                    currency="BRL",
                    note="Arquivo de carteiras simuladas ainda não publicado.",
                )
            )
            continue
        catalog.append(
            PortfolioSummary(
                id=row.wallet,
                name=row.label,
                kind="simulated",
                status="available",
                rule=_WALLET_RULES[wallet],
                experimental=wallet in {"IA", "REVERSAO"},
                initial_brl=row.initial_brl,
                as_of=row.as_of,
                start=row.start,
                cash_brl=row.cash_brl,
                positions_brl=row.positions_brl,
                total_brl=row.total_brl,
                return_pct=row.return_pct,
                n_coins=row.n_coins,
                n_buys=row.n_buys,
                n_sells=row.n_sells,
                n_pending=row.n_pending,
                n_not_executed=row.n_not_executed,
                currency=row.currency,
                fx_close=row.fx_close,
                note="Dinheiro fictício, sem ordens reais.",
            )
        )
    catalog.append(
        PortfolioSummary(
            id="DCA",
            name="DCA fixo",
            kind="reference",
            status="reference",
            rule="Aporte fixo a cada 7 dias no laboratório de estratégias. Não é uma carteira simulada em reais.",
            experimental=False,
            initial_brl=1000.0,
            currency="BRL",
            note="Referência do laboratório; sem patrimônio ou posições em tempo real.",
        )
    )
    return catalog


def _dca_metrics() -> list[PortfolioMetric]:
    metrics: list[PortfolioMetric] = []
    for row in load_lab():
        if row.strategy != "DCA fixo" or row.universe != "PRINCIPAIS":
            continue
        metrics.extend(
            [
                PortfolioMetric(name="Retorno", period=row.period, value=row.total_return_pct, unit="pct"),
                PortfolioMetric(name="Queda máxima", period=row.period, value=row.max_drawdown_pct, unit="pct"),
                PortfolioMetric(name="Sharpe", period=row.period, value=row.sharpe, unit="ratio"),
            ]
        )
    return metrics


def portfolios() -> PortfolioListResponse:
    catalog = _catalog()
    return PortfolioListResponse(
        portfolios=catalog,
        data_available=any(item.status == "available" for item in catalog),
        note=(
            "As quatro carteiras simuladas dependem de sim_wallets.parquet e sim_wallet_positions.parquet. "
            "Sem esses arquivos, nenhum valor é inventado. O DCA é uma referência do laboratório, não uma carteira em reais."
        ),
        generated_at=now_utc(),
    )


def portfolio_detail(portfolio_id: str) -> PortfolioDetail:
    pid = portfolio_id.upper()
    summary = next((item for item in _catalog() if item.id == pid), None)
    if summary is None:
        raise KeyError(portfolio_id)
    if pid == "DCA":
        return PortfolioDetail(
            portfolio=summary,
            positions=[],
            metrics=_dca_metrics(),
            source="frontend/public/strategy_lab.parquet",
            note="Métricas históricas do laboratório. Não há caixa, posições ou curva de patrimônio desta carteira.",
        )
    positions = [
        SimPosition(
            portfolio_id=pid,
            symbol=row.symbol,
            n_lots=row.n_lots,
            first_buy=row.first_buy,
            qty=row.qty,
            cost_brl=row.cost_brl,
            avg_price_usdt=row.avg_price_usdt,
            last_close_usdt=row.last_close_usdt,
            value_brl=row.value_brl,
            return_pct=row.return_pct,
            pnl_brl=row.pnl_brl,
        )
        for row in (
            SimWalletPositionRow.model_validate(item)
            for item in optional_records(public_file("sim_wallet_positions.parquet"))
        )
        if row.wallet == pid
    ]
    return PortfolioDetail(
        portfolio=summary,
        positions=positions,
        metrics=[],
        source="frontend/public/sim_wallets.parquet",
        note=(
            "Posições e caixa são reconstruídos pelo pipeline a partir das decisões; "
            "a API apenas lê o resumo publicado."
            if summary.status == "available"
            else "Arquivo ausente. Rode o pipeline com --record-state para começar o placar; nada é preenchido artificialmente."
        ),
    )


def state_available() -> bool:
    return (STATE_DIR / "positions.parquet").is_file()
