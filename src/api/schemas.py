"""Contratos públicos da API. Espelham os Parquets lidos; nenhum campo é inventado."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Stage = Literal["COMPRAR", "PREPARAR", "NEUTRO", "INDISPONÍVEL"]
Opportunity = Literal["BOA_RELATIVA", "MODERADA", "AGUARDAR", "EVITAR"]
Regime = Literal["FAVORAVEL", "NEUTRO", "DEFENSIVO", "INDISPONIVEL"]
Decision = Literal["NAO_INVESTIR", "APORTE_PEQUENO", "APORTE_PARCIAL", "APORTE_AMPLO"]
DataStatus = Literal["OK", "PARCIAL", "INDISPONIVEL"]
EvidenceStatus = Literal["VALIDADA", "NAO_VALIDADA", "SEM_EVIDENCIA", "REVOGADA", "NAO_AVALIADA"]
EntryLevel = Literal["VALIDADO", "PROMISSOR", "SEM_EVIDENCIA"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DailySignal(ApiModel):
    timestamp: datetime
    symbol: str
    close: float
    sma_90: float | None = None
    zscore_90: float | None = None
    sma_200: float | None = None
    rsi_14: float | None = None
    market_cap_usd: float | None = None
    total_volume_usd: float | None = None
    fng_value: float | None = None
    fng_classification: str | None = None
    regime_up: bool
    uptrend: bool
    panic: bool
    stage: Stage
    stage_reason: str | None = None
    prev_stage: Stage | None = None
    alert: str | None = None
    history_days: int | None = None
    gap_days_365: int | None = None
    avg_volume_30d_usd: float | None = None
    ret_7d_pct: float | None = None
    ret_30d_pct: float | None = None
    ret_90d_pct: float | None = None
    rel_btc_90d_pct: float | None = None
    rel_eth_90d_pct: float | None = None
    vol_90d_pct: float | None = None
    drawdown_now_pct: float | None = None
    drawdown_days: int | None = None
    max_drawdown_180d_pct: float | None = None
    sma_50: float | None = None
    stretch_50: float | None = None
    stability_50d_pct: float | None = None
    conditions_met: int
    conditions_total: int
    conditions: list[str] = Field(default_factory=list)
    score: float | None = None
    score_momentum: float | None = None
    score_stability: float | None = None
    score_risk: float | None = None
    score_liquidity: float | None = None
    est_cost_pct: float | None = None
    opportunity: Opportunity
    candidate_rank: int | None = None
    selected: bool
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    target_fraction: float
    theoretical_brl: float
    allocation_brl: float
    allocation_note: str | None = None
    entry_level: EntryLevel | None = None
    entry_combos: list[str] = Field(default_factory=list)
    entry_new: bool
    entry_since: datetime | None = None
    run_ts: datetime


class Recommendation(ApiModel):
    run_ts: datetime
    data_day: datetime | None = None
    budget_brl: float
    budget_mode: str
    regime: Regime
    regime_filter: str
    regime_close: float | None = None
    regime_sma_200: float | None = None
    total_brl: float
    unallocated_brl: float
    theoretical_total_brl: float
    capped_by_budget: bool
    decision: Decision
    n_analyzed: int
    n_candidates: int
    n_selected: int
    n_funded: int
    notes: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    evidence: str
    data_status: DataStatus
    data_notes: list[str] = Field(default_factory=list)


class Performance(ApiModel):
    universe: str
    strategy: str
    period: str
    start: datetime
    end: datetime
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    sharpe: float | None = None
    invested_pct: float


class SelectionPerformance(ApiModel):
    strategy: str
    period: str
    start: datetime | None = None
    end: datetime | None = None
    total_return_pct: float | None = None
    annual_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    sharpe: float | None = None
    invested_pct: float | None = None
    turnover_per_year: float | None = None
    n_trades: int | None = None
    cost_pct: float | None = None
    rebalance_days: int | None = None


class MarketRegime(ApiModel):
    timestamp: datetime
    known_at: datetime
    symbol: str
    close: float | None = None
    dist_ma_pct: float | None = None
    slope_ma_pct: float | None = None
    vol_ann_pct: float | None = None
    vol_rank_pct: float | None = None
    trend_raw: str | None = None
    trend_regime: str
    vol_regime: str
    status: str
    vol_status: str
    legacy_regime: Regime | None = None
    classifier_version: str
    params_hash: str
    data_fingerprint: str


class Forecast(ApiModel):
    symbol: str
    horizon_days: int
    role: str
    method: str
    params: str
    window_days: int
    n_obs: int
    asof: datetime
    last_close: float
    expected_return_pct: float
    vol_pct: float
    daily_vol_pct: float
    p10_pct: float
    p50_pct: float
    p90_pct: float
    p10_price: float
    p50_price: float
    p90_price: float
    n_eval: int
    test_start: datetime
    test_end: datetime
    mae_pct: float
    rmse_pct: float
    directional_acc: float
    coverage: float
    coverage_nominal: float
    coverage_ok: bool
    width_pct: float
    pinball_pct: float
    base_mae_pct: float
    base_rmse_pct: float
    base_directional_acc: float
    base_coverage: float
    base_width_pct: float
    base_pinball_pct: float
    beats_baseline: bool
    verdict: str


class SourceEvent(ApiModel):
    source: str
    scope: str
    updated_at: datetime
    status: str
    rows: int
    last_data_ts: datetime | None = None
    detail: str


class SignalEvidence(ApiModel):
    symbol: str
    status: EvidenceStatus
    holdout: str
    n_independent_7: int | None = None
    n_independent_30: int | None = None
    excess_7: float | None = None
    excess_30: float | None = None
    ci_low_7: float | None = None
    ci_low_30: float | None = None
    p_holm_7: float | None = None
    p_holm_30: float | None = None
    holdout_n_7: int | None = None
    holdout_n_30: int | None = None
    holdout_excess_7: float | None = None
    holdout_excess_30: float | None = None
    reason: str


class EntryLevelRow(ApiModel):
    combo: str
    candidate: str
    kind: str
    level: EntryLevel
    dev_level: EntryLevel
    holdout: str
    excess_7: float | None = None
    ci_low_7: float | None = None
    ci_high_7: float | None = None
    p_holm_7: float | None = None
    n_signals_7: int
    excess_30: float | None = None
    ci_low_30: float | None = None
    ci_high_30: float | None = None
    p_holm_30: float | None = None
    n_signals_30: int
    holdout_n_7: int | None = None
    holdout_n_30: int | None = None
    holdout_excess_7: float | None = None
    holdout_excess_30: float | None = None
    reason: str


class LabResult(ApiModel):
    universe: str
    strategy: str
    params: str
    period: str
    selected_on: str
    start: datetime
    end: datetime
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    sharpe: float | None = None
    invested_pct: float
    n_trades: int | None = None
    win_rate_pct: float | None = None
    profit_factor: float | None = None
    turnover_per_year: float | None = None
    fee_cost_pct: float | None = None
    beats_random_pct: float | None = None
    random_sims: int | None = None


class Candle(ApiModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    trades: int | None = None


class ArtifactStatus(ApiModel):
    name: str
    path: str
    status: Literal["ok", "missing", "stale"]
    rows: int | None = None
    updated_at: datetime | None = None
    last_data_ts: datetime | None = None
    note: str | None = None


class SystemStatus(ApiModel):
    status: Literal["ok", "partial", "unavailable"]
    generated_at: datetime
    last_run: datetime | None = None
    data_day: datetime | None = None
    api_version: str = "v1"
    source_health: list[SourceEvent] = Field(default_factory=list)
    artifacts: list[ArtifactStatus] = Field(default_factory=list)
    state_branch: str
    note: str


class OverviewResponse(ApiModel):
    recommendation: Recommendation
    signals: list[DailySignal]
    performance: list[Performance]
    selection_performance: list[SelectionPerformance]
    forecast: list[Forecast]
    market: MarketRegime | None = None
    system: SystemStatus
    generated_at: datetime


class SignalsResponse(ApiModel):
    run_ts: datetime
    recommendation: Recommendation
    signals: list[DailySignal]


class MarketBrief(ApiModel):
    as_of: datetime | None = None
    regime: Regime
    regime_label: str
    fng_value: float | None = None
    fng_classification: str | None = None
    btc_close: float | None = None
    btc_sma_200: float | None = None
    btc_distance_pct: float | None = None
    breadth_up: int
    breadth_down: int
    n_analyzed: int
    n_selected: int
    total_allocated_brl: float


class AssetSummary(ApiModel):
    symbol: str
    base: str
    name: str
    close: float | None = None
    ret_7d_pct: float | None = None
    ret_30d_pct: float | None = None
    ret_90d_pct: float | None = None
    vol_90d_pct: float | None = None
    score: float | None = None
    stage: Stage | None = None
    opportunity: Opportunity | None = None
    selected: bool
    allocation_brl: float
    in_analysis: bool


class AssetDetail(ApiModel):
    symbol: str
    base: str
    name: str
    source: str
    first_date: datetime | None = None
    last_date: datetime | None = None
    rows: int
    candles: list[Candle]
    analysis: DailySignal | None = None
    eligibility_note: str
    universe_note: str


class MarketResponse(ApiModel):
    brief: MarketBrief
    assets: list[AssetSummary]
    btc_candles: list[Candle]
    regime_history: list[MarketRegime]
    forecasts: list[Forecast]
    sources: list[SourceEvent]
    generated_at: datetime


class StudyMetric(ApiModel):
    name: str
    period: str
    value: float | None = None
    unit: str
    benchmark: float | None = None
    note: str | None = None


class StudyFinding(ApiModel):
    title: str
    detail: str
    tone: Literal["positive", "neutral", "warning", "critical"]


class ResearchStudy(ApiModel):
    id: str
    title: str
    category: str
    status: Literal["validado", "promissor", "inconclusivo", "rejeitado", "compativel_com_sorte", "experimental"]
    status_label: str
    summary: str
    question: str
    periods: str
    universe: str
    sample: str
    docs: list[str]
    metrics: list[StudyMetric]
    findings: list[StudyFinding]
    limitations: list[str]
    updated_at: str


class EvidenceSummary(ApiModel):
    total: int
    validated: int
    not_validated: int
    no_evidence: int
    revoked: int
    not_evaluated: int
    validated_symbols: list[str]


class ResearchResponse(ApiModel):
    studies: list[ResearchStudy]
    lab: list[LabResult]
    entry_levels: list[EntryLevelRow]
    evidence: EvidenceSummary
    generated_at: datetime


class PortfolioMetric(ApiModel):
    name: str
    period: str
    value: float | None = None
    unit: str
    benchmark: float | None = None
    note: str | None = None


class PortfolioSummary(ApiModel):
    id: str
    name: str
    kind: Literal["simulated", "reference"]
    status: Literal["available", "unavailable", "reference"]
    rule: str
    experimental: bool
    initial_brl: float
    as_of: datetime | None = None
    start: datetime | None = None
    cash_brl: float | None = None
    positions_brl: float | None = None
    total_brl: float | None = None
    return_pct: float | None = None
    n_coins: int | None = None
    n_buys: int | None = None
    n_sells: int | None = None
    n_pending: int | None = None
    n_not_executed: int | None = None
    currency: str
    fx_close: float | None = None
    note: str


class SimPosition(ApiModel):
    portfolio_id: str
    symbol: str
    n_lots: int
    first_buy: datetime | None = None
    qty: float
    cost_brl: float
    avg_price_usdt: float
    last_close_usdt: float
    value_brl: float
    return_pct: float | None = None
    pnl_brl: float | None = None


class PortfolioDetail(ApiModel):
    portfolio: PortfolioSummary
    positions: list[SimPosition]
    metrics: list[PortfolioMetric]
    source: str
    note: str


class PortfolioListResponse(ApiModel):
    portfolios: list[PortfolioSummary]
    data_available: bool
    note: str
    generated_at: datetime

class SimWalletSummaryRow(ApiModel):
    wallet: str
    label: str
    start: datetime
    as_of: datetime
    initial_brl: float
    cash_brl: float
    positions_usdt: float
    positions_brl: float
    total_brl: float
    return_pct: float
    n_coins: int
    n_buys: int
    n_sells: int
    n_pending: int
    n_not_executed: int
    currency: str
    fx_close: float | None = None


class SimWalletPositionRow(ApiModel):
    wallet: str
    symbol: str
    n_lots: int
    first_buy: datetime
    qty: float
    cost_brl: float
    cost_usdt: float
    avg_price_usdt: float
    last_close_usdt: float
    value_usdt: float
    value_brl: float
    return_pct: float | None = None
    pnl_brl: float | None = None