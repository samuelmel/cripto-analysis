/**
 * Linhas dos arquivos publicados pelo pipeline em public/.
 * Espelham os schemas Python — mudou lá, muda aqui no mesmo commit:
 *   DailySignal   daily_alerts.DAILY_SCHEMA        (daily_signals.parquet)
 *   HistoryPoint  anomaly_detector.HISTORY_SCHEMA  (history.parquet)
 *   Trade         trade_simulator.BACKTEST_SCHEMA  (backtest.parquet)
 *   Position      position_advisor.POSITION_SCHEMA (positions.parquet)
 */

export const STAGES = ["COMPRAR", "PREPARAR", "NEUTRO"] as const;
export type Stage = (typeof STAGES)[number];

export const ALERTS = ["COMPRAR AGORA", "NO RADAR", "SAIU DO RADAR"] as const;
export type Alert = (typeof ALERTS)[number];

export const EXIT_REASONS = ["STOP", "PROTEGER LUCRO", "ALVO", "SOBRECOMPRADO", "TEMPO"] as const;
export type ExitReason = (typeof EXIT_REASONS)[number];

export const STRATEGIES = ["SINAL", "REFERENCIA"] as const;
export type Strategy = (typeof STRATEGIES)[number];

export const TRADE_STATUSES = ["FECHADA", "ABERTA"] as const;
export type TradeStatus = (typeof TRADE_STATUSES)[number];

export const ACTIONS = ["VENDER", "SEGURAR"] as const;
export type Action = (typeof ACTIONS)[number];

export interface DailySignal {
  readonly timestamp: Date;
  readonly symbol: string;
  readonly close: number;
  readonly sma_90: number | null;
  readonly zscore_90: number | null;
  readonly rsi_14: number | null;
  readonly market_cap_usd: number | null;
  readonly total_volume_usd: number | null;
  readonly fng_value: number | null;
  readonly fng_classification: string | null;
  readonly buy_signal: boolean;
  readonly stage: Stage;
  readonly prev_stage: Stage | null;
  readonly alert: Alert | null;
}

export interface HistoryPoint {
  readonly timestamp: Date;
  readonly symbol: string;
  readonly close: number;
  readonly sma_90: number | null;
  readonly zscore_90: number | null;
  readonly rsi_14: number | null;
  readonly fng_value: number | null;
  readonly stage: Stage;
}

export interface Trade {
  readonly strategy: Strategy;
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
  readonly trail_price: number | null;
  readonly target_price: number | null;
}

export interface Dashboard {
  readonly signals: readonly DailySignal[];
  readonly history: readonly HistoryPoint[];
  readonly trades: readonly Trade[];
  readonly positions: readonly Position[];
}
