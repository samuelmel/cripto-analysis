/**
 * Escrita das suas posições pela rota local do dev server (server/positionsApi.ts).
 * Só funciona com `npm run dev`; o build estático não tem servidor para gravar.
 */

export class ApiError extends Error {
  override name = "ApiError";
}

export interface NewPurchase {
  readonly symbol: string;
  readonly price: number;
  readonly qty: number;
  readonly date: string; // AAAA-MM-DD
}

export interface Sale {
  readonly price: number;
  readonly date: string;
}

async function call(url: string, method: "POST" | "DELETE", body?: object): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new ApiError("Não foi possível falar com o servidor do painel. Ele está rodando (npm run dev)?");
  }
  if (resp.ok) return;
  const payload: unknown = await resp.json().catch(() => null);
  const message =
    typeof payload === "object" && payload !== null && "error" in payload && typeof payload.error === "string"
      ? payload.error
      : `erro ${resp.status}`;
  throw new ApiError(message);
}

export const addPurchase = (p: NewPurchase): Promise<void> => call("/api/positions", "POST", p);

export const registerSale = (id: string, s: Sale): Promise<void> =>
  call(`/api/positions/${encodeURIComponent(id)}/close`, "POST", s);

export const deletePosition = (id: string): Promise<void> =>
  call(`/api/positions/${encodeURIComponent(id)}`, "DELETE");
