import {
  ACTIONS,
  ALERTS,
  EXIT_REASONS,
  STAGES,
  STRATEGIES,
  TRADE_STATUSES,
  type Dashboard,
  type DailySignal,
  type HistoryPoint,
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
  rsi_14: numOrNull(r, "rsi_14"),
  market_cap_usd: numOrNull(r, "market_cap_usd"),
  total_volume_usd: numOrNull(r, "total_volume_usd"),
  fng_value: numOrNull(r, "fng_value"),
  fng_classification: strOrNull(r, "fng_classification"),
  buy_signal: bool(r, "buy_signal"),
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
  rsi_14: numOrNull(r, "rsi_14"),
  fng_value: numOrNull(r, "fng_value"),
  stage: oneOf(STAGES, r, "stage"),
});

const parseTrade = (r: Row): Trade => ({
  strategy: oneOf(STRATEGIES, r, "strategy"),
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
  trail_price: numOrNull(r, "trail_price"),
  target_price: numOrNull(r, "target_price"),
});

/** Único ponto de I/O do frontend: baixa e valida tudo que o pipeline publicou. */
export async function loadDashboard(base = ""): Promise<Dashboard> {
  const [signals, history, trades, positions] = await Promise.all([
    fetchRows(`${base}/daily_signals.parquet`),
    fetchRows(`${base}/history.parquet`),
    fetchRows(`${base}/backtest.parquet`),
    fetchRows(`${base}/positions.parquet`),
  ]);
  return {
    signals: signals.map(parseSignal),
    history: history.map(parseHistory),
    trades: trades.map(parseTrade),
    positions: positions.map(parsePosition),
  };
}
