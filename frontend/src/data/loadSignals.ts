import { asyncBufferFromUrl, parquetReadObjects } from "hyparquet";
import type { DailySignal } from "../types/signals";

export const SIGNALS_URL = "/daily_signals.parquet";

export class SignalSchemaError extends Error {
  override name = "SignalSchemaError";
}

type Row = Readonly<Record<string, unknown>>;

/** Int64 do Pandas chega como bigint; float NaN chega como NaN. Ambos viram number | null. */
function toNumber(value: unknown): number | null {
  if (typeof value === "bigint") return Number(value);
  if (typeof value === "number") return Number.isNaN(value) ? null : value;
  return null;
}

function requireNumber(row: Row, key: string): number {
  const n = toNumber(row[key]);
  if (n === null) throw new SignalSchemaError(`Coluna "${key}" inválida ou nula`);
  return n;
}

function requireString(row: Row, key: string): string {
  const v = row[key];
  if (typeof v !== "string") throw new SignalSchemaError(`Coluna "${key}" deveria ser string`);
  return v;
}

function toDate(value: unknown): Date {
  if (value instanceof Date) return value;
  throw new SignalSchemaError('Coluna "timestamp" deveria ser data');
}

export function parseSignal(row: Row): DailySignal {
  const buy = row["buy_signal"];
  if (typeof buy !== "boolean") throw new SignalSchemaError('Coluna "buy_signal" deveria ser boolean');
  const fng = row["fng_classification"];
  return {
    timestamp: toDate(row["timestamp"]),
    symbol: requireString(row, "symbol"),
    close: requireNumber(row, "close"),
    sma_90: toNumber(row["sma_90"]),
    zscore_90: toNumber(row["zscore_90"]),
    rsi_14: toNumber(row["rsi_14"]),
    market_cap_usd: toNumber(row["market_cap_usd"]),
    total_volume_usd: toNumber(row["total_volume_usd"]),
    fng_value: toNumber(row["fng_value"]),
    fng_classification: typeof fng === "string" ? fng : null,
    buy_signal: buy,
  };
}

/** Único ponto de I/O do frontend: baixa e valida o snapshot diário. */
export async function loadSignals(url: string = SIGNALS_URL): Promise<readonly DailySignal[]> {
  const file = await asyncBufferFromUrl({ url });
  const rows: readonly unknown[] = await parquetReadObjects({ file });
  return rows.map((row) => {
    if (typeof row !== "object" || row === null) throw new SignalSchemaError("Linha não é objeto");
    return parseSignal(row as Row);
  });
}

/** Ativos com sinal de compra, do mais sobrevendido (menor z-score) ao menos. */
export function undervalued(signals: readonly DailySignal[]): readonly DailySignal[] {
  return signals
    .filter((s) => s.buy_signal)
    .toSorted((a, b) => (a.zscore_90 ?? 0) - (b.zscore_90 ?? 0));
}
