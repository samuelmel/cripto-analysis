/**
 * Uma linha de public/daily_signals.parquet.
 * Espelha OUTPUT_SCHEMA de src/transformers/anomaly_detector.py — mudou lá, muda aqui no mesmo commit.
 */
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

export const STAGES = ["COMPRAR", "PREPARAR", "NEUTRO"] as const;
export type Stage = (typeof STAGES)[number];

export const ALERTS = ["COMPRAR AGORA", "NO RADAR", "SAIU DO RADAR"] as const;
export type Alert = (typeof ALERTS)[number];
