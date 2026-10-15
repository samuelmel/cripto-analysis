import {
  ACTIONS,
  ALERTS,
  EXIT_REASONS,
  FORECAST_ROLES,
  LAB_PERIODS,
  PERIODS,
  PORTFOLIOS,
  STAGES,
  SOURCE_STATUSES,
  STRATEGIES,
  TRADE_STATUSES,
  type ClosedPosition,
  type Dashboard,
  type DailySignal,
  type Forecast,
  type HistoryPoint,
  type LabResult,
  type Performance,
  type Position,
  type SourceEvent,
  type Trade,
} from "../types/signals";
import {
  bool,
  date,
  dateOrNull,
  fetchRows,
  MissingFileError,
  num,
  numOrNull,
  oneOf,
  oneOfOrNull,
  str,
  strOrNull,
  type Row,
} from "./parquet";

export { MissingFileError } from "./parquet";

const parseSignal = (r: Row): DailySignal => ({
  timestamp: date(r, "timestamp"),
  symbol: str(r, "symbol"),
  close: num(r, "close"),
  sma_90: numOrNull(r, "sma_90"),
  zscore_90: numOrNull(r, "zscore_90"),
  sma_200: numOrNull(r, "sma_200"),
  rsi_14: numOrNull(r, "rsi_14"),
  market_cap_usd: numOrNull(r, "market_cap_usd"),
  total_volume_usd: numOrNull(r, "total_volume_usd"),
  fng_value: numOrNull(r, "fng_value"),
  fng_classification: strOrNull(r, "fng_classification"),
  regime_up: bool(r, "regime_up"),
  uptrend: bool(r, "uptrend"),
  panic: bool(r, "panic"),
  stage: oneOf(STAGES, r, "stage"),
  stage_reason: strOrNull(r, "stage_reason"),
  prev_stage: oneOfOrNull(STAGES, r, "prev_stage"),
  alert: oneOfOrNull(ALERTS, r, "alert"),
});

const parseHistory = (r: Row): HistoryPoint => ({
  timestamp: date(r, "timestamp"),
  symbol: str(r, "symbol"),
  close: num(r, "close"),
  sma_90: numOrNull(r, "sma_90"),
  zscore_90: numOrNull(r, "zscore_90"),
  sma_200: numOrNull(r, "sma_200"),
  rsi_14: numOrNull(r, "rsi_14"),
  fng_value: numOrNull(r, "fng_value"),
  regime_up: bool(r, "regime_up"),
  uptrend: bool(r, "uptrend"),
  panic: bool(r, "panic"),
  stage: oneOf(STAGES, r, "stage"),
});

const parsePerformance = (r: Row): Performance => ({
  universe: oneOf(PORTFOLIOS, r, "universe"),
  strategy: oneOf(STRATEGIES, r, "strategy"),
  period: oneOf(PERIODS, r, "period"),
  start: date(r, "start"),
  end: date(r, "end"),
  total_return_pct: num(r, "total_return_pct"),
  annual_return_pct: num(r, "annual_return_pct"),
  max_drawdown_pct: num(r, "max_drawdown_pct"),
  sharpe: numOrNull(r, "sharpe"),
  invested_pct: num(r, "invested_pct"),
});

const parseTrade = (r: Row): Trade => ({
  trade_id: str(r, "trade_id"),
  symbol: str(r, "symbol"),
  entry_ts: date(r, "entry_ts"),
  entry_price: num(r, "entry_price"),
  status: oneOf(TRADE_STATUSES, r, "status"),
  exit_ts: dateOrNull(r, "exit_ts"),
  exit_price: numOrNull(r, "exit_price"),
  exit_reason: oneOfOrNull(EXIT_REASONS, r, "exit_reason"),
  return_pct: numOrNull(r, "return_pct"),
  days_held: numOrNull(r, "days_held"),
});

const parseForecast = (r: Row): Forecast => ({
  symbol: str(r, "symbol"),
  horizon_days: num(r, "horizon_days"),
  role: oneOf(FORECAST_ROLES, r, "role"),
  method: str(r, "method"),
  params: str(r, "params"),
  window_days: num(r, "window_days"),
  n_obs: num(r, "n_obs"),
  asof: date(r, "asof"),
  last_close: num(r, "last_close"),
  expected_return_pct: num(r, "expected_return_pct"),
  vol_pct: num(r, "vol_pct"),
  daily_vol_pct: num(r, "daily_vol_pct"),
  p10_pct: num(r, "p10_pct"),
  p50_pct: num(r, "p50_pct"),
  p90_pct: num(r, "p90_pct"),
  p10_price: num(r, "p10_price"),
  p50_price: num(r, "p50_price"),
  p90_price: num(r, "p90_price"),
  n_eval: num(r, "n_eval"),
  test_start: date(r, "test_start"),
  test_end: date(r, "test_end"),
  mae_pct: num(r, "mae_pct"),
  rmse_pct: num(r, "rmse_pct"),
  directional_acc: num(r, "directional_acc"),
  coverage: num(r, "coverage"),
  coverage_nominal: num(r, "coverage_nominal"),
  coverage_ok: bool(r, "coverage_ok"),
  width_pct: num(r, "width_pct"),
  pinball_pct: num(r, "pinball_pct"),
  base_mae_pct: num(r, "base_mae_pct"),
  base_rmse_pct: num(r, "base_rmse_pct"),
  base_directional_acc: num(r, "base_directional_acc"),
  base_coverage: num(r, "base_coverage"),
  base_width_pct: num(r, "base_width_pct"),
  base_pinball_pct: num(r, "base_pinball_pct"),
  beats_baseline: bool(r, "beats_baseline"),
  verdict: str(r, "verdict"),
});

const parseSource = (r: Row): SourceEvent => ({
  source: str(r, "source"),
  scope: str(r, "scope"),
  updated_at: date(r, "updated_at"),
  status: oneOf(SOURCE_STATUSES, r, "status"),
  rows: num(r, "rows"),
  last_data_ts: dateOrNull(r, "last_data_ts"),
  detail: strOrNull(r, "detail") ?? "",
});

const parseLab = (r: Row): LabResult => ({
  universe: oneOf(PORTFOLIOS, r, "universe"),
  strategy: str(r, "strategy"),
  params: strOrNull(r, "params") ?? "",
  period: oneOf(LAB_PERIODS, r, "period"),
  selected_on: str(r, "selected_on"),
  start: date(r, "start"),
  end: date(r, "end"),
  total_return_pct: num(r, "total_return_pct"),
  annual_return_pct: num(r, "annual_return_pct"),
  max_drawdown_pct: num(r, "max_drawdown_pct"),
  sharpe: numOrNull(r, "sharpe"),
  invested_pct: num(r, "invested_pct"),
  n_trades: numOrNull(r, "n_trades"),
  win_rate_pct: numOrNull(r, "win_rate_pct"),
  profit_factor: numOrNull(r, "profit_factor"),
  turnover_per_year: numOrNull(r, "turnover_per_year"),
  fee_cost_pct: numOrNull(r, "fee_cost_pct"),
  beats_random_pct: numOrNull(r, "beats_random_pct"),
  random_sims: numOrNull(r, "random_sims"),
});

const parsePosition = (r: Row): Position => ({
  position_id: str(r, "position_id"),
  symbol: str(r, "symbol"),
  entry_ts: date(r, "entry_ts"),
  entry_price: num(r, "entry_price"),
  qty: num(r, "qty"),
  last_close: numOrNull(r, "last_close"),
  return_pct: numOrNull(r, "return_pct"),
  max_return_pct: numOrNull(r, "max_return_pct"),
  pnl_usd: numOrNull(r, "pnl_usd"),
  value_usd: numOrNull(r, "value_usd"),
  action: oneOf(ACTIONS, r, "action"),
  reason: oneOfOrNull(EXIT_REASONS, r, "reason"),
  signal_ts: dateOrNull(r, "signal_ts"),
  stop_price: numOrNull(r, "stop_price"),
  sell_below_price: numOrNull(r, "sell_below_price"),
  above_sma_pct: numOrNull(r, "above_sma_pct"),
  data_note: strOrNull(r, "data_note"),
});

const parseClosed = (r: Row): ClosedPosition => ({
  position_id: str(r, "position_id"),
  symbol: str(r, "symbol"),
  entry_ts: date(r, "entry_ts"),
  entry_price: num(r, "entry_price"),
  qty: num(r, "qty"),
  exit_ts: date(r, "exit_ts"),
  exit_price: num(r, "exit_price"),
  return_pct: num(r, "return_pct"),
  pnl_usd: num(r, "pnl_usd"),
});

/** Arquivo opcional: se ainda não existe, a tela mostra o estado vazio em vez de erro. */
async function optionalRows(url: string): Promise<readonly Row[]> {
  try {
    return await fetchRows(url);
  } catch (err) {
    if (err instanceof MissingFileError) return [];
    throw err;
  }
}

/** Leitura: baixa e valida tudo que o pipeline publicou (a escrita fica em api.ts). */
export async function loadDashboard(base = ""): Promise<Dashboard> {
  const [signals, history, trades, performance, forecast, sources, lab, positions, closed] = await Promise.all([
    fetchRows(`${base}/daily_signals.parquet`),
    fetchRows(`${base}/history.parquet`),
    fetchRows(`${base}/backtest.parquet`),
    fetchRows(`${base}/performance.parquet`),
    optionalRows(`${base}/forecast.parquet`),
    optionalRows(`${base}/sources.parquet`),
    optionalRows(`${base}/strategy_lab.parquet`),
    fetchRows(`${base}/positions.parquet`),
    fetchRows(`${base}/closed_positions.parquet`),
  ]);
  return {
    signals: signals.map(parseSignal),
    history: history.map(parseHistory),
    trades: trades.map(parseTrade),
    performance: performance.map(parsePerformance),
    forecast: forecast.map(parseForecast),
    sources: sources.map(parseSource),
    lab: lab.map(parseLab),
    positions: positions.map(parsePosition),
    closed: closed.map(parseClosed),
  };
}
