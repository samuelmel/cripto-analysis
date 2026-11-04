import { describe, expect, it } from "vitest";

import {
  REGIME_LABEL,
  STAGE_LABEL,
  baseOf,
  brl,
  dateShort,
  decisionLabel,
  entryLabel,
  lagDays,
  number,
  pct,
  price,
  regimeTone,
  toneForNumber,
} from "./format";

describe("formatação pt-BR", () => {
  it("formata reais sem esconder centavos", () => {
    expect(brl(1234.5, 2)).toContain("1.234,50");
    expect(brl(100, 0)).toContain("100");
  });

  it("formata percentuais com sinal e arredondamento", () => {
    expect(pct(1.234)).toBe("+1,2%");
    expect(pct(-1.234)).toBe("−1,2%");
    expect(pct(0)).toBe("0,0%");
    expect(pct(null)).toBe("—");
  });

  it("escolhe casas decimais pelo tamanho do preço", () => {
    expect(price(1234.56)).toBe("US$ 1.235");
    expect(price(12.345)).toBe("US$ 12,35");
    expect(price(0.0123)).toBe("US$ 0,0123");
  });

  it("usa ponto para milhar e vírgula para decimal", () => {
    expect(number(1234.5, 1)).toBe("1.234,5");
  });

  it("calcula defasagem em dias UTC", () => {
    expect(lagDays("2026-10-17", new Date("2026-11-03T12:00:00Z"))).toBe(17);
    expect(lagDays("2026-11-03", new Date("2026-11-03T23:59:59Z"))).toBe(0);
    expect(lagDays(null)).toBeNull();
    expect(lagDays("inválida")).toBeNull();
  });

  it("formata datas sem quebrar entradas inválidas", () => {
    expect(dateShort("2026-10-17")).toMatch(/17/);
    expect(dateShort("2026-10-17")).toMatch(/2026/);
    expect(dateShort("x")).toBe("—");
  });
});

describe("rótulos de domínio", () => {
  it("traduz decisões e níveis", () => {
    expect(decisionLabel("APORTE_PARCIAL")).toBe("Aporte parcial");
    expect(decisionLabel("DESCONHECIDA")).toBe("DESCONHECIDA");
    expect(entryLabel("PROMISSOR")).toBe("Em observação");
    expect(entryLabel(null)).toBe("Sem nível");
  });

  it("mapeia estágios e regimes conhecidos", () => {
    expect(STAGE_LABEL.NEUTRO).toBe("Ficar de fora");
    expect(REGIME_LABEL.DEFENSIVO).toBe("Defensivo");
    expect(regimeTone("DEFENSIVO")).toBe("warning");
    expect(regimeTone("FAVORAVEL")).toBe("positive");
  });

  it("classifica números e símbolos", () => {
    expect(toneForNumber(1)).toBe("positive");
    expect(toneForNumber(-1)).toBe("critical");
    expect(toneForNumber(0)).toBe("neutral");
    expect(baseOf("BTC/USDT")).toBe("BTC");
  });
});
