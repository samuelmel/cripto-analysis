import { parquetReadObjects } from "hyparquet";
import { ALERTS, STAGES, type Alert, type DailySignal, type Stage } from "../types/signals";

export const SIGNALS_URL = "/daily_signals.parquet";

export class SignalSchemaError extends Error {
  override name = "SignalSchemaError";
}

/** O arquivo ainda não existe (o dev server devolve index.html no lugar) ou não é Parquet. */
export class SignalsMissingError extends Error {
  override name = "SignalsMissingError";
}

type Row = Readonly<Record<string, unknown>>;

const PARQUET_MAGIC = "PAR1";

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

function oneOf<T extends string>(allowed: readonly T[], value: unknown): T | null {
  return allowed.find((a) => a === value) ?? null;
}

function requireStage(row: Row): Stage {
  const stage = oneOf(STAGES, row["stage"]);
  if (stage === null) throw new SignalSchemaError(`Estágio desconhecido: ${String(row["stage"])}`);
  return stage;
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
    stage: requireStage(row),
    prev_stage: oneOf(STAGES, row["prev_stage"]),
    alert: oneOf<Alert>(ALERTS, row["alert"]),
  };
}

async function fetchParquet(url: string): Promise<ArrayBuffer> {
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) throw new SignalsMissingError(`HTTP ${resp.status} ao buscar ${url}`);
  const buffer = await resp.arrayBuffer();
  const magic = new TextDecoder().decode(new Uint8Array(buffer, 0, Math.min(4, buffer.byteLength)));
  if (magic !== PARQUET_MAGIC) throw new SignalsMissingError(`${url} não existe ou não é Parquet`);
  return buffer;
}

/** Único ponto de I/O do frontend: baixa e valida o snapshot diário. */
export async function loadSignals(url: string = SIGNALS_URL): Promise<readonly DailySignal[]> {
  const file = await fetchParquet(url);
  const rows: readonly unknown[] = await parquetReadObjects({ file });
  return rows.map((row) => {
    if (typeof row !== "object" || row === null) throw new SignalSchemaError("Linha não é objeto");
    return parseSignal(row as Row);
  });
}

const byZscore = (a: DailySignal, b: DailySignal): number => (a.zscore_90 ?? 0) - (b.zscore_90 ?? 0);

export function byStage(signals: readonly DailySignal[], stage: Stage): readonly DailySignal[] {
  return signals.filter((s) => s.stage === stage).toSorted(byZscore);
}

export function withAlert(signals: readonly DailySignal[], alert: Alert): readonly DailySignal[] {
  return signals.filter((s) => s.alert === alert).toSorted(byZscore);
}
