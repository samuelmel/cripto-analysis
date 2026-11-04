import type { Opportunity, Regime, Stage, Tone } from "../schemas/api";

const compactFormatter = new Intl.NumberFormat("pt-BR", {
  notation: "compact",
  maximumFractionDigits: 1,
});

const dateFormatter = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const dateTimeFormatter = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "America/Fortaleza",
});

export const DASH = "—";

export function brl(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function number(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${number(Math.abs(value), digits)}%`;
}

export function pointPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${number(Math.abs(value), digits)} p.p.`;
}

export function ratio(value: number | null | undefined, digits = 2): string {
  return number(value, digits);
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return compactFormatter.format(value);
}

export function usd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value >= 1000 ? 0 : 4,
  }).format(value);
}

export function price(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  const digits = value >= 1000 ? 0 : value >= 1 ? 2 : value >= 0.01 ? 4 : 6;
  return `US$ ${number(value, digits)}`;
}

export function dateShort(value: string | null | undefined): string {
  if (!value) return DASH;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? DASH : dateFormatter.format(date).replace(".", "");
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return DASH;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? DASH : dateTimeFormatter.format(date).replace(".", "");
}

export function lagDays(value: string | null | undefined, now = new Date()): number | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const day = 86_400_000;
  return Math.max(0, Math.round((Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) - Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())) / day));
}

export function toneForNumber(value: number | null | undefined): Tone {
  if (value === null || value === undefined || value === 0) return "neutral";
  return value > 0 ? "positive" : "critical";
}

export const STAGE_LABEL: Record<Stage, string> = {
  COMPRAR: "Comprar ou segurar",
  PREPARAR: "No radar",
  NEUTRO: "Ficar de fora",
  INDISPONÍVEL: "Sem dados",
};

export const OPPORTUNITY_LABEL: Record<Opportunity, string> = {
  BOA_RELATIVA: "Boa oportunidade",
  MODERADA: "Moderada",
  AGUARDAR: "Aguardar",
  EVITAR: "Evitar",
};

export const REGIME_LABEL: Record<Regime, string> = {
  FAVORAVEL: "Favorável",
  NEUTRO: "Neutro",
  DEFENSIVO: "Defensivo",
  INDISPONIVEL: "Sem dados",
};

export function decisionLabel(decision: string): string {
  switch (decision) {
    case "NAO_INVESTIR":
      return "Não investir";
    case "APORTE_PEQUENO":
      return "Aporte pequeno";
    case "APORTE_PARCIAL":
      return "Aporte parcial";
    case "APORTE_AMPLO":
      return "Aporte amplo";
    default:
      return decision;
  }
}

export function entryLabel(level: string | null): string {
  switch (level) {
    case "VALIDADO":
      return "Validado";
    case "PROMISSOR":
      return "Em observação";
    case "SEM_EVIDENCIA":
      return "Sem evidência";
    default:
      return "Sem nível";
  }
}

export function studyStatusLabel(status: string): string {
  switch (status) {
    case "validado":
      return "Validado";
    case "promissor":
      return "Promissor";
    case "inconclusivo":
      return "Inconclusivo";
    case "rejeitado":
      return "Rejeitado";
    case "compativel_com_sorte":
      return "Compatível com sorte";
    case "experimental":
      return "Experimental";
    default:
      return status;
  }
}

export const TONE_CLASS: Record<Tone, string> = {
  positive: "text-good bg-good-wash border-good/20",
  neutral: "text-muted bg-sunken border-hairline",
  warning: "text-warning bg-warning-wash border-warning/20",
  critical: "text-critical bg-critical-wash border-critical/20",
};

export function stageTone(stage: Stage | null): Tone {
  if (stage === "COMPRAR") return "positive";
  if (stage === "PREPARAR" || stage === "INDISPONÍVEL") return "warning";
  return "neutral";
}

export function opportunityTone(opportunity: Opportunity | null): Tone {
  if (opportunity === "BOA_RELATIVA") return "positive";
  if (opportunity === "AGUARDAR") return "warning";
  if (opportunity === "EVITAR") return "critical";
  return "neutral";
}

export function regimeTone(regime: Regime): Tone {
  if (regime === "FAVORAVEL") return "positive";
  if (regime === "DEFENSIVO" || regime === "INDISPONIVEL") return "warning";
  return "neutral";
}

export function evidenceTone(status: string): Tone {
  if (status === "VALIDADA" || status === "validado") return "positive";
  if (status === "PROMISSOR" || status === "promissor") return "warning";
  if (status === "REVOGADA" || status === "rejeitado") return "critical";
  return "neutral";
}

export function baseOf(symbol: string): string {
  return symbol.split("/", 1)[0] ?? symbol;
}

export function plural(value: number, singular: string, pluralForm: string): string {
  return value === 1 ? singular : pluralForm;
}
