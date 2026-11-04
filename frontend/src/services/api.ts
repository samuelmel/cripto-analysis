import type { z } from "zod";

const BASE = "/api/v1";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function getJson<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: "application/json" },
    signal: signal ?? null,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(body.trim() === "" ? `Falha HTTP ${response.status}` : body, response.status);
  }
  const payload: unknown = await response.json();
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    const first = parsed.error.issues[0];
    const where = first?.path.join(".") ?? "resposta";
    throw new ApiError(`Contrato inválido em ${where}: ${first?.message ?? "formato inesperado"}`, 502);
  }
  return parsed.data;
}
