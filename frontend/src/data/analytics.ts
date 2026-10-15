import type { Alert, DailySignal, ExitReason, HistoryPoint, Position, Stage, Strategy, Trade } from "../types/signals";

/* ---------- estatística do backtest ---------- */

export interface TradeSummary {
  readonly count: number;
  readonly winRate: number | null;
  readonly mean: number | null;
  readonly median: number | null;
  readonly worst: number | null;
  readonly best: number | null;
  readonly meanDays: number | null;
}

const mean = (xs: readonly number[]): number | null =>
  xs.length === 0 ? null : xs.reduce((a, b) => a + b, 0) / xs.length;

function median(xs: readonly number[]): number | null {
  if (xs.length === 0) return null;
  const s = xs.toSorted((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  const hi = s[mid] ?? 0;
  return s.length % 2 === 0 ? ((s[mid - 1] ?? hi) + hi) / 2 : hi;
}

/** Estatísticas das operações já encerradas (abertas não têm resultado final). */
export function summarize(trades: readonly Trade[]): TradeSummary {
  const closed = trades.filter((t) => t.status === "FECHADA");
  const rets = closed.flatMap((t) => (t.return_pct === null ? [] : [t.return_pct]));
  const days = closed.flatMap((t) => (t.days_held === null ? [] : [t.days_held]));
  return {
    count: rets.length,
    winRate: rets.length === 0 ? null : (rets.filter((r) => r > 0).length / rets.length) * 100,
    mean: mean(rets),
    median: median(rets),
    worst: rets.length === 0 ? null : Math.min(...rets),
    best: rets.length === 0 ? null : Math.max(...rets),
    meanDays: mean(days),
  };
}

export const byStrategy = (trades: readonly Trade[], strategy: Strategy): readonly Trade[] =>
  trades.filter((t) => t.strategy === strategy);

export function byReason(trades: readonly Trade[]): ReadonlyMap<ExitReason, TradeSummary> {
  const groups = Map.groupBy(
    trades.filter((t) => t.exit_reason !== null),
    (t) => t.exit_reason as ExitReason,
  );
  return new Map([...groups].map(([reason, ts]) => [reason, summarize(ts)]));
}

/** Sinal sem vantagem: retorno médio do SINAL abaixo da REFERÊNCIA (compra sem critério). */
export function signalHasEdge(signal: TradeSummary, reference: TradeSummary): boolean | null {
  if (signal.mean === null || reference.mean === null) return null;
  return signal.mean > reference.mean;
}

/* ---------- seleção ---------- */

const byZscore = (a: DailySignal, b: DailySignal): number => (a.zscore_90 ?? 0) - (b.zscore_90 ?? 0);

export const byStage = (signals: readonly DailySignal[], stage: Stage): readonly DailySignal[] =>
  signals.filter((s) => s.stage === stage).toSorted(byZscore);

export const withAlert = (signals: readonly DailySignal[], alert: Alert): readonly DailySignal[] =>
  signals.filter((s) => s.alert === alert).toSorted(byZscore);

export const allByZscore = (signals: readonly DailySignal[]): readonly DailySignal[] => signals.toSorted(byZscore);

export const historyOf = (history: readonly HistoryPoint[], symbol: string): readonly HistoryPoint[] =>
  history.filter((h) => h.symbol === symbol);

/* ---------- tradução para leigos ---------- */

export const coinName = (symbol: string): string => symbol.replace("/USDT", "");

/** Distância do preço para a média de 90 dias, em %. Negativo = abaixo do normal. */
export const distanceFromAverage = (close: number, sma: number | null): number | null =>
  sma === null || sma === 0 ? null : (close / sma - 1) * 100;

export type Tone = "good" | "critical" | "warning" | "neutral" | "signal";

export function momentumLabel(rsi: number | null): { readonly text: string; readonly tone: Tone } {
  if (rsi === null) return { text: "sem dados", tone: "neutral" };
  if (rsi < 30) return { text: "caiu rápido demais", tone: "warning" };
  if (rsi > 70) return { text: "subiu rápido demais", tone: "warning" };
  return { text: "ritmo normal", tone: "neutral" };
}

const FNG_PT: Record<string, string> = {
  "Extreme Fear": "medo extremo",
  Fear: "medo",
  Neutral: "neutro",
  Greed: "ganância",
  "Extreme Greed": "ganância extrema",
};

export const fngLabel = (classification: string | null): string =>
  classification === null ? "sem leitura" : FNG_PT[classification] ?? classification.toLowerCase();

export const fngTone = (value: number | null): Tone =>
  value === null ? "neutral" : value < 25 ? "critical" : value < 45 ? "warning" : value > 75 ? "warning" : "neutral";

export const STAGE_LABEL: Record<Stage, { readonly text: string; readonly tone: Tone }> = {
  COMPRAR: { text: "Zona de compra", tone: "signal" },
  PREPARAR: { text: "Ficar de olho", tone: "warning" },
  NEUTRO: { text: "Normal", tone: "neutral" },
};

/** Descreve o momento em que a regra disparou (o preço pode ter mudado depois). */
export const REASON_TEXT: Record<ExitReason, string> = {
  STOP: "caiu 20% em relação ao preço de compra — o limite de perda foi atingido",
  "PROTEGER LUCRO": "depois de subir 15%, devolveu 10% a partir do pico — era hora de garantir o lucro",
  ALVO: "voltou ao preço médio dos últimos 90 dias com lucro — a recuperação esperada aconteceu",
  SOBRECOMPRADO: "subiu rápido demais enquanto estava com lucro — era um bom momento para realizar",
  TEMPO: "180 dias se passaram sem nenhuma outra regra disparar — libere o dinheiro",
};

/** A regra em si, para a explicação de como funciona. */
export const RULE_TEXT: Record<ExitReason, string> = {
  STOP: "se o preço cair 20% abaixo do que você pagou, venda para não perder mais",
  "PROTEGER LUCRO": "se subir 15% ou mais e depois recuar 10% a partir do pico, venda para garantir o lucro",
  ALVO: "se você comprou abaixo da média de 90 dias e o preço voltou a ela com lucro, a recuperação aconteceu: venda",
  SOBRECOMPRADO: "se subir rápido demais (RSI acima de 70) e você estiver no lucro, realize",
  TEMPO: "se 180 dias passarem sem nenhuma das anteriores, venda e libere o dinheiro",
};

export const REASON_SHORT: Record<ExitReason, string> = {
  STOP: "Limite de perda",
  "PROTEGER LUCRO": "Garantir lucro",
  ALVO: "Recuperou",
  SOBRECOMPRADO: "Subiu demais",
  TEMPO: "Tempo esgotado",
};

export interface Verdict {
  readonly tone: Tone;
  readonly headline: string;
  readonly details: readonly string[];
}

/** O que fazer hoje, em uma frase principal e algumas linhas de apoio. */
export function todayVerdict(signals: readonly DailySignal[], positions: readonly Position[]): Verdict {
  const toSell = positions.filter((p) => p.action === "VENDER");
  const buy = byStage(signals, "COMPRAR");
  const watch = byStage(signals, "PREPARAR");
  const details = [
    ...toSell.map((p) => `Venda ${coinName(p.symbol)}: ${p.reason === null ? "a regra de saída disparou" : REASON_TEXT[p.reason]}.`),
    ...buy.map((s) => `${coinName(s.symbol)} entrou na zona de compra: caiu muito abaixo do normal e o mercado está em pânico.`),
    ...(watch.length > 0
      ? [`${list(watch.map((s) => coinName(s.symbol)))} ${watch.length === 1 ? "está caindo" : "estão caindo"} em direção à zona de compra. Ainda não é hora.`]
      : []),
  ];
  if (toSell.length > 0) {
    return { tone: "critical", headline: `Você tem ${plural(toSell.length, "moeda para vender", "moedas para vender")}.`, details };
  }
  if (buy.length > 0) {
    return { tone: "signal", headline: `${list(buy.map((s) => coinName(s.symbol)))} na zona de compra hoje.`, details };
  }
  if (watch.length > 0) {
    return { tone: "warning", headline: `Nada para comprar ainda, mas ${plural(watch.length, "moeda merece", "moedas merecem")} atenção.`, details };
  }
  const holding = positions.length > 0 ? " Suas posições podem continuar como estão." : "";
  return {
    tone: "neutral",
    headline: "Nada a fazer hoje.",
    details: [`Nenhuma moeda está perto da zona de compra.${holding}`],
  };
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

function list(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} e ${items.at(-1) ?? ""}`;
}

/* ---------- formatação pt-BR ---------- */

const nf = (opts: Intl.NumberFormatOptions): Intl.NumberFormat => new Intl.NumberFormat("pt-BR", opts);
const PRICE = nf({ maximumSignificantDigits: 6 });
const USD = nf({ style: "currency", currency: "USD" });
const DATE = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

export const fmt = {
  num: (n: number | null, digits = 2): string => (n === null ? "—" : nf({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n)),
  pct: (n: number | null, digits = 1): string =>
    n === null ? "—" : `${n > 0 ? "+" : n < 0 ? "−" : ""}${nf({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Math.abs(n))}%`,
  price: (n: number | null): string => (n === null ? "—" : `US$ ${PRICE.format(n)}`),
  usd: (n: number | null): string => (n === null ? "—" : USD.format(n)),
  day: (d: Date | null): string => (d === null ? "—" : DATE.format(d).replace(/ de /g, " ").replace(".", "")),
};

export const signTone = (n: number | null): Tone => (n === null || n === 0 ? "neutral" : n > 0 ? "good" : "critical");

/* ---------- apoio a gráficos e formulários ---------- */

/** Fechamentos dos últimos `days` candles de uma moeda, do mais antigo ao mais recente. */
export const recentCloses = (history: readonly HistoryPoint[], symbol: string, days = 90): readonly number[] =>
  history.filter((h) => h.symbol === symbol).slice(-days).map((h) => h.close);

/** Data de hoje no fuso local, no formato AAAA-MM-DD (para inputs de data). */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Converte texto digitado ("1.234,5" ou "1234.5") em número; null se inválido. */
export function parseAmount(text: string): number | null {
  const t = text.trim();
  if (t === "") return null;
  const normalized = t.includes(",") ? t.replace(/\./g, "").replace(",", ".") : t;
  const n = Number(normalized);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Número para um campo de texto no padrão brasileiro, sem separador de milhar ("2421,6"). */
export const toInput = (n: number): string => String(n).replace(".", ",");
