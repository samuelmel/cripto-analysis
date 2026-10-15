/**
 * Linhas dos arquivos publicados pelo pipeline em public/.
 * Espelham os schemas Python — mudou lá, muda aqui no mesmo commit:
 *   DailySignal   daily_alerts.DAILY_SCHEMA        (daily_signals.parquet)
 *   HistoryPoint  anomaly_detector.HISTORY_SCHEMA  (history.parquet)
 *   Trade         trade_simulator.TRADE_SCHEMA     (backtest.parquet)
 *   Performance   trade_simulator.PERFORMANCE_SCHEMA (performance.parquet)
 *   Forecast      forecast.FORECAST_SCHEMA         (forecast.parquet)
 *   Position      position_advisor.POSITION_SCHEMA (positions.parquet)
 */

export const STAGES = ["COMPRAR", "PREPARAR", "NEUTRO", "INDISPONÍVEL"] as const;
export type Stage = (typeof STAGES)[number];

export const ALERTS = ["COMPRAR AGORA", "VENDER AGORA", "NO RADAR", "SAIU DO RADAR"] as const;
export type Alert = (typeof ALERTS)[number];

export const EXIT_REASONS = ["STOP", "TENDENCIA", "MERCADO"] as const;
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

export interface Dashboard {
  readonly signals: readonly DailySignal[];
  readonly history: readonly HistoryPoint[];
  readonly trades: readonly Trade[];
  readonly performance: readonly Performance[];
  readonly positions: readonly Position[];
  readonly closed: readonly ClosedPosition[];
}
