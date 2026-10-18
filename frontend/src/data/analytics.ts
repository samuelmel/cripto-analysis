import type {
  Alert,
  DailySignal,
  ExitReason,
  Forecast,
  HistoryPoint,
  LabPeriod,
  LabResult,
  Performance,
  Period,
  Portfolio,
  SourceEvent,
  Stage,
  Strategy,
  Trade,
} from "../types/signals";

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

export function byReason(trades: readonly Trade[]): ReadonlyMap<ExitReason, TradeSummary> {
  const groups = Map.groupBy(
    trades.filter((t) => t.exit_reason !== null),
    (t) => t.exit_reason as ExitReason,
  );
  return new Map([...groups].map(([reason, ts]) => [reason, summarize(ts)]));
}

/* ---------- carteira: tendência x comprar e segurar ---------- */

export const performanceOf = (
  rows: readonly Performance[],
  universe: Portfolio,
  strategy: Strategy,
  period: Period,
): Performance | null => rows.find((r) => r.universe === universe && r.strategy === strategy && r.period === period) ?? null;

export const STRATEGY_NAME: Record<Strategy, string> = {
  TENDENCIA: "Regra de tendência",
  COMPRAR_E_SEGURAR: "Comprar e segurar",
  PANICO: "Regra antiga: comprar no pânico",
};

export const PERIOD_NAME: Record<Period, string> = { TREINO: "Treino", TESTE: "Teste" };

/** "2018–2022": os anos que o período realmente cobre nos dados. */
export function periodYears(rows: readonly Performance[], period: Period): string {
  const r = rows.find((x) => x.period === period);
  return r === undefined ? "" : `${r.start.getUTCFullYear()}–${r.end.getUTCFullYear()}`;
}

export type TrendVerdict = "better" | "safer" | "worse";

/**
 * A regra de tendência contra comprar e segurar, nos dois períodos:
 *   better  rendeu mais nos dois;
 *   safer   rendeu menos em algum, mas ao menos 70% do rendimento anual de comprar e segurar
 *           e com queda máxima menor nos dois;
 *   worse   nenhum dos dois.
 */
export function trendVerdict(rows: readonly Performance[], universe: Portfolio): TrendVerdict | null {
  const pairs = (["TREINO", "TESTE"] as const).map((period) => ({
    trend: performanceOf(rows, universe, "TENDENCIA", period),
    hold: performanceOf(rows, universe, "COMPRAR_E_SEGURAR", period),
  }));
  const complete = pairs.flatMap((p) => (p.trend === null || p.hold === null ? [] : [{ trend: p.trend, hold: p.hold }]));
  if (complete.length < 2) return null;
  if (complete.every((p) => p.trend.total_return_pct >= p.hold.total_return_pct)) return "better";
  const safer = complete.every(
    (p) =>
      p.trend.annual_return_pct >= 0.7 * p.hold.annual_return_pct &&
      Math.abs(p.trend.max_drawdown_pct) < Math.abs(p.hold.max_drawdown_pct),
  );
  return safer ? "safer" : "worse";
}

/* ---------- seleção ---------- */

const byZscore = (a: DailySignal, b: DailySignal): number => (a.zscore_90 ?? 0) - (b.zscore_90 ?? 0);

export const byStage = (signals: readonly DailySignal[], stage: Stage): readonly DailySignal[] =>
  signals.filter((s) => s.stage === stage).toSorted(byZscore);

export const withAlert = (signals: readonly DailySignal[], alert: Alert): readonly DailySignal[] =>
  signals.filter((s) => s.alert === alert).toSorted(byZscore);

export const historyOf = (history: readonly HistoryPoint[], symbol: string): readonly HistoryPoint[] =>
  history.filter((h) => h.symbol === symbol);

/* ---------- tradução para leigos ---------- */

export const coinName = (symbol: string): string => symbol.replace("/USDT", "");

/** Distância do preço para uma média móvel, em %. Negativo = abaixo da média. */
export const distanceFromAverage = (close: number, sma: number | null): number | null =>
  sma === null || sma === 0 ? null : (close / sma - 1) * 100;

export type Tone = "good" | "critical" | "warning" | "neutral" | "signal";

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
  COMPRAR: { text: "Comprar ou segurar", tone: "good" },
  PREPARAR: { text: "Ficar de olho", tone: "warning" },
  NEUTRO: { text: "Ficar de fora", tone: "neutral" },
  INDISPONÍVEL: { text: "Sem dados confiáveis", tone: "warning" },
};

/** Descreve o momento em que a regra disparou (o preço pode ter mudado depois). */
export const REASON_TEXT: Record<ExitReason, string> = {
  STOP: "caiu 20% em relação ao preço de compra — o limite de perda foi atingido",
  TENDENCIA: "o preço fechou abaixo da média dos últimos 200 dias — a tendência de alta acabou",
  MERCADO: "o Bitcoin fechou abaixo da média dos últimos 200 dias — o mercado todo virou para baixo",
  DESLISTAGEM: "a moeda parou de negociar com a posição aberta — a simulação a dá como perdida",
};

/** A regra em si, para a explicação de como funciona. */
export const RULE_TEXT: Record<ExitReason, string> = {
  TENDENCIA: "se o preço fechar o dia abaixo da média dos últimos 200 dias, venda: a tendência de alta acabou",
  MERCADO: "se o Bitcoin fechar abaixo da média dos 200 dias dele, venda também as outras moedas: o mercado virou",
  STOP: "se o preço cair 20% abaixo do que você pagou, venda para não perder mais (proteção extra)",
  DESLISTAGEM: "não é uma regra de venda: no backtest, moeda que para de negociar com posição aberta conta como perda total",
};

export const REASON_SHORT: Record<ExitReason, string> = {
  STOP: "Limite de perda",
  TENDENCIA: "Tendência acabou",
  MERCADO: "Mercado virou",
  DESLISTAGEM: "Parou de negociar",
};

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

/* ---------- painel: estado, avisos, cartões e previsão ---------- */

const DAY_MS = 86_400_000;

/** Quantos dias o último candle está atrás do último candle fechado esperado (ontem, em UTC). */
export function dataLagDays(lastCandle: Date | null, now: Date): number | null {
  if (lastCandle === null) return null;
  const expected = Math.floor(now.getTime() / DAY_MS) * DAY_MS - DAY_MS;
  const last = Math.floor(lastCandle.getTime() / DAY_MS) * DAY_MS;
  return Math.round((expected - last) / DAY_MS);
}

/** Última atualização das fontes: quando a coleta mais recente aconteceu e quantas falharam. */
export function lastCollection(sources: readonly SourceEvent[]): { readonly at: Date | null; readonly failures: number } {
  const at = sources.reduce<Date | null>((m, e) => (m === null || e.updated_at > m ? e.updated_at : m), null);
  return { at, failures: sources.filter((e) => e.status === "erro").length };
}

export const NO_EDGE = "sem vantagem demonstrada sobre o preço de hoje";

/** Previsão do modelo (não do baseline) de uma moeda, do horizonte curto ao longo. */
export const modelForecast = (rows: readonly Forecast[], symbol: string): readonly Forecast[] =>
  rows.filter((f) => f.symbol === symbol && f.role === "MODELO").toSorted((a, b) => a.horizon_days - b.horizon_days);

export const horizonName = (days: number): string => (days === 1 ? "Amanhã" : `Em ${days} dias`);

/** Posição de um valor numa escala simétrica em torno de zero, de 0 a 100 (50 = zero). */
export const bandPercent = (value: number, limit: number): number => 50 + (Math.max(-limit, Math.min(limit, value)) / limit) * 50;

/** Resultados do laboratório de um universo e período, sem as linhas de sorteio, do maior Sharpe ao menor. */
export function labRows(rows: readonly LabResult[], universe: Portfolio, period: LabPeriod): readonly LabResult[] {
  return rows
    .filter((r) => r.universe === universe && r.period === period && !r.strategy.startsWith("Aleatória"))
    .toSorted((a, b) => (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity));
}

/** Data e hora no fuso de Fortaleza, ex.: "15 out 2026 21:10". */
export function fmtDateTime(d: Date | null): string {
  if (d === null) return "—";
  const f = new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Fortaleza",
  });
  return f.format(d).replace(/ de /g, " ").replace(".", "").replace(",", "");
}

/** Número com casas fixas; Infinity (nenhuma operação perdedora) vira texto. */
export const fmtRatio = (n: number | null, digits = 1): string =>
  n === null ? "—" : n === Infinity ? "sem perdas" : nf({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
