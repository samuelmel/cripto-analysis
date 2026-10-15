/**
 * Rota local do dev server para registrar compras e vendas pelo painel.
 *
 *   POST   /api/positions             { symbol, price, qty, date? }  registra compra
 *   POST   /api/positions/:id/close   { price, date? }               registra venda
 *   DELETE /api/positions/:id                                        apaga registro
 *
 * Borda de I/O (CLAUDE.md §1): só valida a entrada e chama `python -m src.positions`, que guarda
 * os dados e reanalisa a base local. Executa sem shell e só aceita pedidos da própria página
 * (cabeçalho Origin igual ao host), para nenhum outro site aberto no navegador conseguir usar.
 */
import { execFile } from "node:child_process";
import type { IncomingMessage, ServerResponse } from "node:http";
import path from "node:path";
import type { Plugin } from "vite";

const PROJECT_ROOT = path.resolve(import.meta.dirname, "..", "..");
const UV = process.env["UV_BIN"] ?? "uv";
const TIMEOUT_MS = 120_000;
const MAX_BODY = 4_096;

const SYMBOL = /^[A-Z0-9]{2,10}\/USDT$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[0-9a-f]{8}$/;

class BadRequest extends Error {}

function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk: Buffer) => {
      body += chunk.toString("utf8");
      if (body.length > MAX_BODY) reject(new BadRequest("corpo grande demais"));
    });
    req.on("end", () => {
      if (body === "") return resolve({});
      try {
        const parsed: unknown = JSON.parse(body);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new BadRequest("JSON inválido");
        resolve(parsed as Record<string, unknown>);
      } catch {
        reject(new BadRequest("JSON inválido"));
      }
    });
    req.on("error", reject);
  });
}

function positive(value: unknown, field: string): string {
  const n = typeof value === "number" ? value : typeof value === "string" ? Number(value.replace(",", ".")) : NaN;
  if (!Number.isFinite(n) || n <= 0) throw new BadRequest(`${field} deve ser um número maior que zero`);
  return String(n);
}

function optionalDay(value: unknown): string[] {
  if (value === undefined || value === null || value === "") return [];
  if (typeof value !== "string" || !DAY.test(value)) throw new BadRequest("data deve estar no formato AAAA-MM-DD");
  return ["--date", value];
}

function runPositions(args: readonly string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      UV,
      ["run", "python", "-m", "src.positions", ...args],
      { cwd: PROJECT_ROOT, timeout: TIMEOUT_MS, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: "utf-8" } },
      (err, stdout, stderr) => {
        if (err === null) return resolve(stdout);
        const message = stderr.trim().split(/\r?\n/).at(-1) ?? "";
        reject(new BadRequest(message !== "" ? message : err.message));
      },
    );
  });
}

function send(res: ServerResponse, status: number, payload: Record<string, unknown>): void {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}

function sameOrigin(req: IncomingMessage): boolean {
  const origin = req.headers.origin;
  const host = req.headers.host;
  if (typeof origin !== "string" || typeof host !== "string") return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  if (!sameOrigin(req)) return send(res, 403, { ok: false, error: "origem não permitida" });
  const url = new URL(req.url ?? "/", "http://localhost");
  const parts = url.pathname.replace(/^\/api\/positions\/?/, "").split("/").filter(Boolean);

  try {
    if (req.method === "POST" && parts.length === 0) {
      const body = await readJson(req);
      const symbol = typeof body["symbol"] === "string" ? body["symbol"] : "";
      if (!SYMBOL.test(symbol)) throw new BadRequest("moeda inválida");
      await runPositions(["add", symbol, positive(body["price"], "preço"), positive(body["qty"], "quantidade"), ...optionalDay(body["date"])]);
      return send(res, 201, { ok: true });
    }
    const [id, action] = parts;
    if (id === undefined || !ID.test(id)) throw new BadRequest("registro inválido");
    if (req.method === "POST" && action === "close" && parts.length === 2) {
      const body = await readJson(req);
      await runPositions(["close", id, positive(body["price"], "preço"), ...optionalDay(body["date"])]);
      return send(res, 200, { ok: true });
    }
    if (req.method === "DELETE" && parts.length === 1) {
      await runPositions(["remove", id]);
      return send(res, 200, { ok: true });
    }
    return send(res, 404, { ok: false, error: "rota não encontrada" });
  } catch (err) {
    const status = err instanceof BadRequest ? 400 : 500;
    return send(res, status, { ok: false, error: err instanceof Error ? err.message : String(err) });
  }
}

export function positionsApi(): Plugin {
  return {
    name: "crypto-analyzer:positions-api",
    configureServer(server) {
      server.middlewares.use("/api/positions", (req, res) => {
        void handle(req, res);
      });
    },
  };
}
