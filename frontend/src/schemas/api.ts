import { z } from "zod";

const numberOrNull = z.number().nullable();
const stringOrNull = z.string().nullable();
const stringList = z.array(z.string());

export const stageSchema = z.enum(["COMPRAR", "PREPARAR", "NEUTRO", "INDISPONÍVEL"]);
export const opportunitySchema = z.enum(["BOA_RELATIVA", "MODERADA", "AGUARDAR", "EVITAR"]);
export const regimeSchema = z.enum(["FAVORAVEL", "NEUTRO", "DEFENSIVO", "INDISPONIVEL"]);
export const toneSchema = z.enum(["positive", "neutral", "warning", "critical"]);

export const signalSchema = z.object({
  timestamp: z.string(),
  symbol: z.string(),
  close: z.number(),
  sma_50: numberOrNull,
  sma_90: numberOrNull,
  sma_200: numberOrNull,
  rsi_14: numberOrNull,
  fng_value: numberOrNull,
  fng_classification: stringOrNull,
  regime_up: z.boolean(),
  uptrend: z.boolean(),
  panic: z.boolean(),
  stage: stageSchema,
  stage_reason: stringOrNull,
  alert: stringOrNull,
  history_days: z.number().int().nullable(),
  gap_days_365: z.number().int().nullable(),
  avg_volume_30d_usd: numberOrNull,
  ret_7d_pct: numberOrNull,
  ret_30d_pct: numberOrNull,
  ret_90d_pct: numberOrNull,
  rel_btc_90d_pct: numberOrNull,
  rel_eth_90d_pct: numberOrNull,
  vol_90d_pct: numberOrNull,
  drawdown_now_pct: numberOrNull,
  drawdown_days: z.number().int().nullable(),
  max_drawdown_180d_pct: numberOrNull,
  stretch_50: numberOrNull,
  stability_50d_pct: numberOrNull,
  conditions_met: z.number().int(),
  conditions_total: z.number().int(),
  conditions: stringList,
  score: numberOrNull,
  score_momentum: numberOrNull,
  score_stability: numberOrNull,
  score_risk: numberOrNull,
  score_liquidity: numberOrNull,
  est_cost_pct: numberOrNull,
  opportunity: opportunitySchema,
  candidate_rank: z.number().int().nullable(),
  selected: z.boolean(),
  reasons: stringList,
  risks: stringList,
  blockers: stringList,
  target_fraction: z.number(),
  theoretical_brl: z.number(),
  allocation_brl: z.number(),
  allocation_note: stringOrNull,
  entry_level: z.enum(["VALIDADO", "PROMISSOR", "SEM_EVIDENCIA"]).nullable(),
  entry_combos: stringList,
  entry_new: z.boolean(),
  entry_since: stringOrNull,
  run_ts: z.string(),
});

export const recommendationSchema = z.object({
  run_ts: z.string(),
  data_day: stringOrNull,
  budget_brl: z.number(),
  budget_mode: z.string(),
  regime: regimeSchema,
  regime_filter: z.string(),
  regime_close: numberOrNull,
  regime_sma_200: numberOrNull,
  total_brl: z.number(),
  unallocated_brl: z.number(),
  theoretical_total_brl: z.number(),
  capped_by_budget: z.boolean(),
  decision: z.enum(["NAO_INVESTIR", "APORTE_PEQUENO", "APORTE_PARCIAL", "APORTE_AMPLO"]),
  n_analyzed: z.number().int(),
  n_candidates: z.number().int(),
  n_selected: z.number().int(),
  n_funded: z.number().int(),
  notes: stringList,
  excluded: stringList,
  evidence: z.string(),
  data_status: z.enum(["OK", "PARCIAL", "INDISPONIVEL"]),
  data_notes: stringList,
});

export const performanceSchema = z.object({
  universe: z.string(),
  strategy: z.string(),
  period: z.string(),
  start: z.string(),
  end: z.string(),
  total_return_pct: z.number(),
  annual_return_pct: z.number(),
  max_drawdown_pct: z.number(),
  sharpe: numberOrNull,
  invested_pct: z.number(),
});

export const selectionPerformanceSchema = z.object({
  strategy: z.string(),
  period: z.string(),
  start: stringOrNull,
  end: stringOrNull,
  total_return_pct: numberOrNull,
  annual_return_pct: numberOrNull,
  max_drawdown_pct: numberOrNull,
  sharpe: numberOrNull,
  invested_pct: numberOrNull,
  n_trades: z.number().int().nullable(),
});

export const forecastSchema = z.object({
  symbol: z.string(),
  horizon_days: z.number().int(),
  role: z.enum(["BASELINE", "MODELO"]),
  method: z.string(),
  asof: z.string(),
  last_close: z.number(),
  expected_return_pct: z.number(),
  p10_price: z.number(),
  p50_price: z.number(),
  p90_price: z.number(),
  beats_baseline: z.boolean(),
  verdict: z.string(),
});

export const sourceSchema = z.object({
  source: z.string(),
  scope: z.string(),
  updated_at: z.string(),
  status: z.enum(["ok", "erro"]),
  rows: z.number().int(),
  last_data_ts: stringOrNull,
  detail: z.string(),
});

export const marketRegimeSchema = z.object({
  timestamp: z.string(),
  known_at: z.string(),
  symbol: z.string(),
  close: numberOrNull,
  dist_ma_pct: numberOrNull,
  slope_ma_pct: numberOrNull,
  vol_ann_pct: numberOrNull,
  vol_rank_pct: numberOrNull,
  trend_regime: z.string(),
  vol_regime: z.string(),
  status: z.string(),
  legacy_regime: regimeSchema.nullable(),
});

export const artifactSchema = z.object({
  name: z.string(),
  path: z.string(),
  status: z.enum(["ok", "missing", "stale"]),
  rows: z.number().int().nullable(),
  updated_at: stringOrNull,
  last_data_ts: stringOrNull,
  note: stringOrNull,
});

export const systemSchema = z.object({
  status: z.enum(["ok", "partial", "unavailable"]),
  generated_at: z.string(),
  last_run: stringOrNull,
  data_day: stringOrNull,
  api_version: z.string(),
  source_health: z.array(sourceSchema),
  artifacts: z.array(artifactSchema),
  state_branch: z.string(),
  note: z.string(),
});

export const overviewSchema = z.object({
  recommendation: recommendationSchema,
  signals: z.array(signalSchema),
  performance: z.array(performanceSchema),
  selection_performance: z.array(selectionPerformanceSchema),
  forecast: z.array(forecastSchema),
  market: marketRegimeSchema.nullable(),
  system: systemSchema,
  generated_at: z.string(),
});

export const signalsSchema = z.object({
  run_ts: z.string(),
  recommendation: recommendationSchema,
  signals: z.array(signalSchema),
});

export const marketBriefSchema = z.object({
  as_of: stringOrNull,
  regime: regimeSchema,
  regime_label: z.string(),
  fng_value: numberOrNull,
  fng_classification: stringOrNull,
  btc_close: numberOrNull,
  btc_sma_200: numberOrNull,
  btc_distance_pct: numberOrNull,
  breadth_up: z.number().int(),
  breadth_down: z.number().int(),
  n_analyzed: z.number().int(),
  n_selected: z.number().int(),
  total_allocated_brl: z.number(),
});

export const assetSummarySchema = z.object({
  symbol: z.string(),
  base: z.string(),
  name: z.string(),
  close: numberOrNull,
  ret_7d_pct: numberOrNull,
  ret_30d_pct: numberOrNull,
  ret_90d_pct: numberOrNull,
  vol_90d_pct: numberOrNull,
  score: numberOrNull,
  stage: stageSchema.nullable(),
  opportunity: opportunitySchema.nullable(),
  selected: z.boolean(),
  allocation_brl: z.number(),
  in_analysis: z.boolean(),
});

export const candleSchema = z.object({
  timestamp: z.string(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number(),
  quote_volume: numberOrNull,
  trades: z.number().int().nullable(),
});

export const assetDetailSchema = z.object({
  symbol: z.string(),
  base: z.string(),
  name: z.string(),
  source: z.string(),
  first_date: stringOrNull,
  last_date: stringOrNull,
  rows: z.number().int(),
  candles: z.array(candleSchema),
  analysis: signalSchema.nullable(),
  eligibility_note: z.string(),
  universe_note: z.string(),
});

export const marketSchema = z.object({
  brief: marketBriefSchema,
  assets: z.array(assetSummarySchema),
  btc_candles: z.array(candleSchema),
  regime_history: z.array(marketRegimeSchema),
  forecasts: z.array(forecastSchema),
  sources: z.array(sourceSchema),
  generated_at: z.string(),
});

export const studyMetricSchema = z.object({
  name: z.string(),
  period: z.string(),
  value: numberOrNull,
  unit: z.string(),
  benchmark: numberOrNull,
  note: stringOrNull,
});

export const studyFindingSchema = z.object({
  title: z.string(),
  detail: z.string(),
  tone: toneSchema,
});

export const researchStudySchema = z.object({
  id: z.string(),
  title: z.string(),
  category: z.string(),
  status: z.enum(["validado", "promissor", "inconclusivo", "rejeitado", "compativel_com_sorte", "experimental"]),
  status_label: z.string(),
  summary: z.string(),
  question: z.string(),
  periods: z.string(),
  universe: z.string(),
  sample: z.string(),
  docs: stringList,
  metrics: z.array(studyMetricSchema),
  findings: z.array(studyFindingSchema),
  limitations: stringList,
  updated_at: z.string(),
});

export const labResultSchema = z.object({
  universe: z.string(),
  strategy: z.string(),
  params: z.string(),
  period: z.string(),
  total_return_pct: z.number(),
  annual_return_pct: z.number(),
  max_drawdown_pct: z.number(),
  sharpe: numberOrNull,
  invested_pct: z.number(),
});

export const entryLevelSchema = z.object({
  combo: z.string(),
  candidate: z.string(),
  kind: z.string(),
  level: z.enum(["VALIDADO", "PROMISSOR", "SEM_EVIDENCIA"]),
  dev_level: z.enum(["VALIDADO", "PROMISSOR", "SEM_EVIDENCIA"]),
  holdout: z.string(),
  excess_7: numberOrNull,
  excess_30: numberOrNull,
  reason: z.string(),
});

export const evidenceSummarySchema = z.object({
  total: z.number().int(),
  validated: z.number().int(),
  not_validated: z.number().int(),
  no_evidence: z.number().int(),
  revoked: z.number().int(),
  not_evaluated: z.number().int(),
  validated_symbols: stringList,
});

export const researchSchema = z.object({
  studies: z.array(researchStudySchema),
  lab: z.array(labResultSchema),
  entry_levels: z.array(entryLevelSchema),
  evidence: evidenceSummarySchema,
  generated_at: z.string(),
});

export const portfolioSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(["simulated", "reference"]),
  status: z.enum(["available", "unavailable", "reference"]),
  rule: z.string(),
  experimental: z.boolean(),
  initial_brl: z.number(),
  as_of: stringOrNull,
  start: stringOrNull,
  cash_brl: numberOrNull,
  positions_brl: numberOrNull,
  total_brl: numberOrNull,
  return_pct: numberOrNull,
  n_coins: z.number().int().nullable(),
  n_buys: z.number().int().nullable(),
  n_sells: z.number().int().nullable(),
  n_pending: z.number().int().nullable(),
  n_not_executed: z.number().int().nullable(),
  currency: z.string(),
  fx_close: numberOrNull,
  note: z.string(),
});

export const portfolioMetricSchema = z.object({
  name: z.string(),
  period: z.string(),
  value: numberOrNull,
  unit: z.string(),
  benchmark: numberOrNull,
  note: stringOrNull,
});

export const simPositionSchema = z.object({
  portfolio_id: z.string(),
  symbol: z.string(),
  n_lots: z.number().int(),
  first_buy: stringOrNull,
  qty: z.number(),
  cost_brl: z.number(),
  avg_price_usdt: z.number(),
  last_close_usdt: z.number(),
  value_brl: z.number(),
  return_pct: numberOrNull,
  pnl_brl: numberOrNull,
});

export const portfolioDetailSchema = z.object({
  portfolio: portfolioSummarySchema,
  positions: z.array(simPositionSchema),
  metrics: z.array(portfolioMetricSchema),
  source: z.string(),
  note: z.string(),
});

export const portfoliosSchema = z.object({
  portfolios: z.array(portfolioSummarySchema),
  data_available: z.boolean(),
  note: z.string(),
  generated_at: z.string(),
});

export type Stage = z.infer<typeof stageSchema>;
export type Opportunity = z.infer<typeof opportunitySchema>;
export type Regime = z.infer<typeof regimeSchema>;
export type Tone = z.infer<typeof toneSchema>;
export type Signal = z.infer<typeof signalSchema>;
export type Recommendation = z.infer<typeof recommendationSchema>;
export type Performance = z.infer<typeof performanceSchema>;
export type SelectionPerformance = z.infer<typeof selectionPerformanceSchema>;
export type Forecast = z.infer<typeof forecastSchema>;
export type SourceEvent = z.infer<typeof sourceSchema>;
export type MarketRegime = z.infer<typeof marketRegimeSchema>;
export type SystemStatus = z.infer<typeof systemSchema>;
export type Overview = z.infer<typeof overviewSchema>;
export type MarketData = z.infer<typeof marketSchema>;
export type AssetSummary = z.infer<typeof assetSummarySchema>;
export type Candle = z.infer<typeof candleSchema>;
export type AssetDetail = z.infer<typeof assetDetailSchema>;
export type StudyMetric = z.infer<typeof studyMetricSchema>;
export type StudyFinding = z.infer<typeof studyFindingSchema>;
export type ResearchStudy = z.infer<typeof researchStudySchema>;
export type LabResult = z.infer<typeof labResultSchema>;
export type EntryLevel = z.infer<typeof entryLevelSchema>;
export type ResearchData = z.infer<typeof researchSchema>;
export type PortfolioSummary = z.infer<typeof portfolioSummarySchema>;
export type PortfolioMetric = z.infer<typeof portfolioMetricSchema>;
export type SimPosition = z.infer<typeof simPositionSchema>;
export type PortfolioDetail = z.infer<typeof portfolioDetailSchema>;
export type PortfoliosData = z.infer<typeof portfoliosSchema>;
