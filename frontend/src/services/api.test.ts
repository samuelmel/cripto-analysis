import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError, getJson } from "./api";

const payloadSchema = z.object({ ok: z.boolean() });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("cliente da API", () => {
  it("valida e devolve a resposta", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getJson("/health", payloadSchema)).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/health",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("transforma HTTP não-ok em ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("indisponível", { status: 503 })));

    await expect(getJson("/overview", payloadSchema)).rejects.toMatchObject({
      name: "ApiError",
      status: 503,
      message: "indisponível",
    });
  });

  it("rejeita contrato inválido com status 502", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: "sim" }), { status: 200 })));

    const error = await getJson("/overview", payloadSchema).catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 502 });
    expect((error as ApiError).message).toContain("Contrato inválido em ok");
  });
});
