import { parquetReadObjects } from "hyparquet";

export type Row = Readonly<Record<string, unknown>>;

export class SchemaError extends Error {
  override name = "SchemaError";
}

/** O arquivo ainda não existe (o dev server devolve index.html no lugar) ou não é Parquet. */
export class MissingFileError extends Error {
  override name = "MissingFileError";
}

const PARQUET_MAGIC = "PAR1";

export async function fetchRows(url: string): Promise<readonly Row[]> {
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) throw new MissingFileError(`HTTP ${resp.status} ao buscar ${url}`);
  const file = await resp.arrayBuffer();
  const magic = new TextDecoder().decode(new Uint8Array(file, 0, Math.min(4, file.byteLength)));
  if (magic !== PARQUET_MAGIC) throw new MissingFileError(`${url} não existe ou não é Parquet`);
  const rows: readonly unknown[] = await parquetReadObjects({ file });
  return rows.map((row) => {
    if (typeof row !== "object" || row === null) throw new SchemaError(`${url}: linha não é objeto`);
    return row as Row;
  });
}

/** Int64 do Pandas chega como bigint; float NaN chega como NaN. Ambos viram number | null. */
export function numOrNull(row: Row, key: string): number | null {
  const v = row[key];
  if (typeof v === "bigint") return Number(v);
  if (typeof v === "number") return Number.isNaN(v) ? null : v;
  return null;
}

export function num(row: Row, key: string): number {
  const n = numOrNull(row, key);
  if (n === null) throw new SchemaError(`coluna "${key}" inválida ou nula`);
  return n;
}

export function strOrNull(row: Row, key: string): string | null {
  const v = row[key];
  return typeof v === "string" ? v : null;
}

export function str(row: Row, key: string): string {
  const v = strOrNull(row, key);
  if (v === null) throw new SchemaError(`coluna "${key}" deveria ser string`);
  return v;
}

export function dateOrNull(row: Row, key: string): Date | null {
  const v = row[key];
  return v instanceof Date && !Number.isNaN(v.getTime()) ? v : null;
}

export function date(row: Row, key: string): Date {
  const v = dateOrNull(row, key);
  if (v === null) throw new SchemaError(`coluna "${key}" deveria ser data`);
  return v;
}

export function bool(row: Row, key: string): boolean {
  const v = row[key];
  if (typeof v !== "boolean") throw new SchemaError(`coluna "${key}" deveria ser boolean`);
  return v;
}

export function oneOfOrNull<T extends string>(allowed: readonly T[], row: Row, key: string): T | null {
  return allowed.find((a) => a === row[key]) ?? null;
}

export function oneOf<T extends string>(allowed: readonly T[], row: Row, key: string): T {
  const v = oneOfOrNull(allowed, row, key);
  if (v === null) throw new SchemaError(`coluna "${key}": valor inesperado ${String(row[key])}`);
  return v;
}
