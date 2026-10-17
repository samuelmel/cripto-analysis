/**
 * Linhas dos arquivos publicados pelo pipeline em public/.
 * Espelham os schemas Python — mudou lá, muda aqui no mesmo commit:
 *   DailySignal   recommendation.SIGNALS_SCHEMA    (daily_signals.parquet: sinal SMA 200 + seleção + aporte)
 *   Recommendation recommendation.RECOMMENDATION_SCHEMA (recommendation.parquet, uma linha)
 *   SelectionPerf selection_backtest.SELECTION_PERF_SCHEMA (selection_backtest.parquet)
 *   MarketRegime  regimes.REGIME_SCHEMA            (market_regimes.parquet, opcional: regime de mercado por dia)
 *   HistoryPoint  anomaly_detector.HISTORY_SCHEMA  (history.parquet)
 *   Trade         trade_simulator.TRADE_SCHEMA     (backtest.parquet)
 *   Performance   trade_simulator.PERFORMANCE_SCHEMA (performance.parquet)
 *   Forecast      forecast.FORECAST_SCHEMA         (forecast.parquet)
 *   SourceEvent   loaders.source_log.SOURCE_LOG_SCHEMA (sources.parquet)
 *   LabResult     research/strategy_lab.RESULT_SCHEMA (strategy_lab.parquet, opcional)
 *   Position      position_advisor.POSITION_SCHEMA (positions.parquet)
 *   SignalEvidence signal_validation.EVIDENCE_SCHEMA (signal_evidence.parquet, opcional: evidência estatística do COMPRAR)
 */

export const STAGES = ["COMPRAR", "PREPARAR", "NEUTRO", "INDISPONÍVEL"] as const;
export type Stage = (typeof STAGES)[number];

export const ALERTS = ["COMPRAR AGORA", "VENDER AGORA", "NO RADAR", "SAIU DO RADAR"] as const;
export type Alert = (typeof ALERTS)[number];

/** DESLISTAGEM: só no backtest (portfolio_backtest.EXIT_DELISTED), quando a moeda para de negociar com posição aberta. */
export const EXIT_REASONS = ["STOP", "TENDENCIA", "MERCADO", "DESLISTAGEM"] as const;
export type ExitReason = (typeof EXIT_REASONS)[number];

export const STRATEGIES = ["TENDENCIA", "COMPRAR_E_SEGURAR", "PANICO"] as const;
export type Strategy = (typeof STRATEGIES)[number];

export const PERIODS = ["TREINO", "TESTE"] as const;
export type Period = (typeof PERIODS)[number];

export const PORTFOLIOS = ["PRINCIPAIS", "TODAS"] as const;
export type Portfolio = (typeof PORTFOLIOS)[number];

export const TRADE_STATUSES = ["FECHADA", "ABERTA"] as const;
export type TradeStatus = (typeof TRADE_STATUSES)[number];

export const ACTIONS = ["VENDER", "SEGURAR", "INDISPONÍVEL"] as const;
export type Action = (typeof ACTIONS)[number];

export const OPPORTUNITIES = ["BOA_RELATIVA", "MODERADA", "AGUARDAR", "EVITAR"] as const;
export type Opportunity = (typeof OPPORTUNITIES)[number];

export const REGIMES = ["FAVORAVEL", "NEUTRO", "DEFENSIVO", "INDISPONIVEL"] as const;
export type Regime = (typeof REGIMES)[number];

/** Regimes de mercado (transformers/regimes.py), separados de `Regime`: outro significado, outro tipo. */
export const MARKET_TREND_REGIMES = ["ALTA", "BAIXA", "LATERAL", "MISTO", "INDETERMINADO", "INDISPONIVEL"] as const;
export type MarketTrendRegime = (typeof MARKET_TREND_REGIMES)[number];

export const MARKET_VOL_REGIMES = ["NORMAL", "ALTA", "INDISPONIVEL"] as const;
export type MarketVolRegime = (typeof MARKET_VOL_REGIMES)[number];

export const REGIME_STATUSES = ["OK", "SEM_CANDLE", "DADO_INVALIDO", "HISTORICO_INSUFICIENTE", "DADOS_INCOMPLETOS"] as const;
export type RegimeStatus = (typeof REGIME_STATUSES)[number];

/** Evidência estatística do sinal COMPRAR por moeda (transformers/signal_validation.py). Só VALIDADA mostra COMPRAR. */
export const EVIDENCE_STATUSES = ["VALIDADA", "NAO_VALIDADA", "SEM_EVIDENCIA", "REVOGADA", "NAO_AVALIADA"] as const;
export type EvidenceStatus = (typeof EVIDENCE_STATUSES)[number];

export const HOLDOUT_STATES = ["CONFIRMADA", "INSUFICIENTE", "REFUTADA", "NAO_APLICA"] as const;
export type HoldoutState = (typeof HOLDOUT_STATES)[number];

export const DECISIONS = ["NAO_INVESTIR", "APORTE_PEQUENO", "APORTE_PARCIAL", "APORTE_AMPLO"] as const;
export type Decision = (typeof DECISIONS)[number];

export const DATA_STATUSES = ["OK", "PARCIAL", "INDISPONIVEL"] as const;
export type DataStatus = (typeof DATA_STATUSES)[number];

export interface DailySignal {
  readonly timestamp: Date;
  readonly symbol: string;
  readonly close: number;
  readonly sma_90: number | null;
  readonly zscore_90: number | null;
  readonly sma_200: number | null;
  readonly rsi_14: number | null;
  readonly market_cap_usd: number | null;
  readonly total_volume_usd: number | null;
  readonly fng_value: number | null;
  readonly fng_classification: string | null;
  readonly regime_up: boolean;
  readonly uptrend: boolean;
  readonly panic: boolean;
  readonly stage: Stage;
  readonly stage_reason: string | null;
  readonly prev_stage: Stage | null;
  readonly alert: Alert | null;
  // seleção (selection.SELECTION_SCHEMA)
  readonly history_days: number | null;
  readonly gap_days_365: number | null;
  readonly avg_volume_30d_usd: number | null;
  readonly ret_7d_pct: number | null;
  readonly ret_30d_pct: number | null;
  readonly ret_90d_pct: number | null;
  readonly rel_btc_90d_pct: number | null;
  readonly rel_eth_90d_pct: number | null;
  readonly vol_90d_pct: number | null;
  readonly drawdown_now_pct: number | null;
  readonly drawdown_days: number | null;
  readonly max_drawdown_180d_pct: number | null;
  readonly sma_50: number | null;
  readonly stretch_50: number | null;
  readonly stability_50d_pct: number | null;
  readonly conditions_met: number;
  readonly conditions_total: number;
  readonly conditions: readonly string[];
  readonly score: number | null;
  readonly score_momentum: number | null;
  readonly score_stability: number | null;
  readonly score_risk: number | null;
  readonly score_liquidity: number | null;
  readonly est_cost_pct: number | null;
  readonly opportunity: Opportunity;
  readonly candidate_rank: number | null;
  readonly selected: boolean;
  readonly reasons: readonly string[];
  readonly risks: readonly string[];
  readonly blockers: readonly string[];
  // aporte (allocation.ALLOCATION_SCHEMA)
  readonly target_fraction: number;
  readonly theoretical_brl: number;
  readonly allocation_brl: number;
  readonly allocation_note: string | null;
  readonly run_ts: Date;
}

/** Uma linha de recommendation.parquet: o resumo da recomendação da mesma execução de daily_signals. */
export interface Recommendation {
  readonly run_ts: Date;
  readonly data_day: Date | null;
  readonly budget_brl: number;
  readonly budget_mode: string;
  readonly regime: Regime;
  readonly regime_filter: string;
  readonly regime_close: number | null;
  readonly regime_sma_200: number | null;
  readonly total_brl: number;
  readonly unallocated_brl: number;
  readonly theoretical_total_brl: number;
  readonly capped_by_budget: boolean;
  readonly decision: Decision;
  readonly n_analyzed: number;
  readonly n_candidates: number;
  readonly n_selected: number;
  readonly n_funded: number;
  readonly notes: readonly string[];
  readonly excluded: readonly string[];
  readonly evidence: string;
  readonly data_status: DataStatus;
  readonly data_notes: readonly string[];
}

export const SELECTION_STRATEGIES = [
  "SELECAO", "SELECAO_PESO_IGUAL", "MOMENTO_SIMPLES", "TENDENCIA_SMA200", "COMPRAR_E_SEGURAR", "BTC",
] as const;
export type SelectionStrategy = (typeof SELECTION_STRATEGIES)[number];

/** Uma linha de selection_backtest.parquet: uma estratégia num período (treino, validação ou teste). */
export interface SelectionPerf {
  readonly strategy: SelectionStrategy;
  readonly period: LabPeriod;
  readonly start: Date | null;
  readonly end: Date | null;
  readonly total_return_pct: number | null;
  readonly annual_return_pct: number | null;
  readonly max_drawdown_pct: number | null;
  readonly sharpe: number | null;
  readonly invested_pct: number | null;
  readonly turnover_per_year: number | null;
  readonly n_trades: number | null;
  readonly cost_pct: number | null;
  readonly rebalance_days: number | null;
}

export interface HistoryPoint {
  readonly timestamp: Date;
  readonly symbol: string;
  readonly close: number;
  readonly sma_90: number | null;
  readonly zscore_90: number | null;
  readonly sma_200: number | null;
  readonly rsi_14: number | null;
  readonly fng_value: number | null;
  readonly regime_up: boolean;
  readonly uptrend: boolean;
  readonly panic: boolean;
  readonly stage: Stage;
}

export interface Trade {
  readonly trade_id: string;
  readonly symbol: string;
  readonly entry_ts: Date;
  readonly entry_price: number;
  readonly status: TradeStatus;
  readonly exit_ts: Date | null;
  readonly exit_price: number | null;
  readonly exit_reason: ExitReason | null;
  readonly return_pct: number | null;
  readonly days_held: number | null;
}

/** Uma linha de performance.parquet: uma estratégia numa carteira e num período. */
export interface Performance {
  readonly universe: Portfolio;
  readonly strategy: Strategy;
  readonly period: Period;
  readonly start: Date;
  readonly end: Date;
  readonly total_return_pct: number;
  readonly annual_return_pct: number;
  readonly max_drawdown_pct: number;
  readonly sharpe: number | null;
  readonly invested_pct: number;
}

export const FORECAST_ROLES = ["BASELINE", "MODELO"] as const;
export type ForecastRole = (typeof FORECAST_ROLES)[number];

/** Uma linha de forecast.parquet: previsão de hoje e avaliação no teste, de um método num horizonte. */
export interface Forecast {
  readonly symbol: string;
  readonly horizon_days: number;
  readonly role: ForecastRole;
  readonly method: string;
  readonly params: string;
  readonly window_days: number;
  readonly n_obs: number;
  readonly asof: Date;
  readonly last_close: number;
  readonly expected_return_pct: number;
  readonly vol_pct: number;
  readonly daily_vol_pct: number;
  readonly p10_pct: number;
  readonly p50_pct: number;
  readonly p90_pct: number;
  readonly p10_price: number;
  readonly p50_price: number;
  readonly p90_price: number;
  readonly n_eval: number;
  readonly test_start: Date;
  readonly test_end: Date;
  readonly mae_pct: number;
  readonly rmse_pct: number;
  readonly directional_acc: number;
  readonly coverage: number;
  readonly coverage_nominal: number;
  readonly coverage_ok: boolean;
  readonly width_pct: number;
  readonly pinball_pct: number;
  readonly base_mae_pct: number;
  readonly base_rmse_pct: number;
  readonly base_directional_acc: number;
  readonly base_coverage: number;
  readonly base_width_pct: number;
  readonly base_pinball_pct: number;
  readonly beats_baseline: boolean;
  readonly verdict: string;
}

export const LAB_PERIODS = ["TREINO", "VALIDACAO", "TESTE"] as const;
export type LabPeriod = (typeof LAB_PERIODS)[number];

export const SOURCE_STATUSES = ["ok", "erro"] as const;
export type SourceStatus = (typeof SOURCE_STATUSES)[number];

/** Uma linha de sources.parquet: a última atualização de uma fonte para um escopo (símbolo ou MARKET). */
export interface SourceEvent {
  readonly source: string;
  readonly scope: string;
  readonly updated_at: Date;
  readonly status: SourceStatus;
  readonly rows: number;
  readonly last_data_ts: Date | null;
  readonly detail: string;
}

/** Uma linha de strategy_lab.parquet: uma estratégia numa carteira e num período (treino, validação ou teste). */
export interface LabResult {
  readonly universe: Portfolio;
  readonly strategy: string;
  readonly params: string;
  readonly period: LabPeriod;
  readonly selected_on: string;
  readonly start: Date;
  readonly end: Date;
  readonly total_return_pct: number;
  readonly annual_return_pct: number;
  readonly max_drawdown_pct: number;
  readonly sharpe: number | null;
  readonly invested_pct: number;
  readonly n_trades: number | null;
  readonly win_rate_pct: number | null;
  readonly profit_factor: number | null;
  readonly turnover_per_year: number | null;
  readonly fee_cost_pct: number | null;
  readonly beats_random_pct: number | null;
  readonly random_sims: number | null;
}

export interface Position {
  readonly position_id: string;
  readonly symbol: string;
  readonly entry_ts: Date;
  readonly entry_price: number;
  readonly qty: number;
  readonly last_close: number | null;
  readonly return_pct: number | null;
  readonly max_return_pct: number | null;
  readonly pnl_usd: number | null;
  readonly value_usd: number | null;
  readonly action: Action;
  readonly reason: ExitReason | null;
  readonly signal_ts: Date | null;
  readonly stop_price: number | null;
  readonly sell_below_price: number | null;
  readonly above_sma_pct: number | null;
  readonly data_note: string | null;
}

/** position_advisor.CLOSED_SCHEMA (closed_positions.parquet) */
export interface ClosedPosition {
  readonly position_id: string;
  readonly symbol: string;
  readonly entry_ts: Date;
  readonly entry_price: number;
  readonly qty: number;
  readonly exit_ts: Date;
  readonly exit_price: number;
  readonly return_pct: number;
  readonly pnl_usd: number;
}

/**
 * Uma linha de market_regimes.parquet: o regime do BTC no dia `timestamp`, conhecido só a partir de `known_at`
 * (fechamento do candle). Não há probabilidade: as regras não são um modelo calibrado.
 */
export interface MarketRegime {
  readonly timestamp: Date;
  readonly known_at: Date;
  readonly symbol: string;
  readonly close: number | null;
  readonly dist_ma_pct: number | null;
  readonly slope_ma_pct: number | null;
  readonly vol_ann_pct: number | null;
  readonly vol_rank_pct: number | null;
  readonly trend_raw: MarketTrendRegime | null;
  readonly trend_regime: MarketTrendRegime;
  readonly vol_regime: MarketVolRegime;
  readonly status: RegimeStatus;
  readonly vol_status: RegimeStatus;
  readonly legacy_regime: Regime | null;
  readonly classifier_version: string;
  readonly params_hash: string;
  readonly data_fingerprint: string;
}

export interface SignalEvidence {
  readonly symbol: string;
  readonly status: EvidenceStatus;
  readonly holdout: HoldoutState;
  readonly n_independent_7: number | null;
  readonly n_independent_30: number | null;
  readonly excess_7: number | null;
  readonly excess_30: number | null;
  readonly ci_low_7: number | null;
  readonly ci_low_30: number | null;
  readonly p_holm_7: number | null;
  readonly p_holm_30: number | null;
  readonly holdout_n_7: number | null;
  readonly holdout_n_30: number | null;
  readonly holdout_excess_7: number | null;
  readonly holdout_excess_30: number | null;
  readonly reason: string;
}

export interface Dashboard {
  readonly signals: readonly DailySignal[];
  readonly recommendation: Recommendation;
  readonly selectionPerf: readonly SelectionPerf[];
  readonly marketRegimes: readonly MarketRegime[];
  readonly history: readonly HistoryPoint[];
  readonly trades: readonly Trade[];
  readonly performance: readonly Performance[];
  readonly forecast: readonly Forecast[];
  readonly sources: readonly SourceEvent[];
  readonly lab: readonly LabResult[];
  readonly positions: readonly Position[];
  readonly closed: readonly ClosedPosition[];
  readonly evidence: readonly SignalEvidence[];
}
