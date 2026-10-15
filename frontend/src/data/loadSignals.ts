import {
  ACTIONS,
  ALERTS,
  EXIT_REASONS,
  PERIODS,
  PORTFOLIOS,
  STAGES,
  STRATEGIES,
  TRADE_STATUSES,
  type ClosedPosition,
  type Dashboard,
  type DailySignal,
  type HistoryPoint,
  type Performance,
  type Position,
  type Trade,
} from "../types/signals";
import {
  bool,
  date,
  dateOrNull,
  fetchRows,
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

/** Leitura: baixa e valida tudo que o pipeline publicou (a escrita fica em api.ts). */
export async function loadDashboard(base = ""): Promise<Dashboard> {
  const [signals, history, trades, performance, positions, closed] = await Promise.all([
    fetchRows(`${base}/daily_signals.parquet`),
    fetchRows(`${base}/history.parquet`),
    fetchRows(`${base}/backtest.parquet`),
    fetchRows(`${base}/performance.parquet`),
    fetchRows(`${base}/positions.parquet`),
    fetchRows(`${base}/closed_positions.parquet`),
  ]);
  return {
    signals: signals.map(parseSignal),
    history: history.map(parseHistory),
    trades: trades.map(parseTrade),
    performance: performance.map(parsePerformance),
    positions: positions.map(parsePosition),
    closed: closed.map(parseClosed),
  };
}
