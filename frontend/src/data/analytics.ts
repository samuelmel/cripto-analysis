import type { Alert, DailySignal, ExitReason, HistoryPoint, Stage, Strategy, Trade } from "../types/signals";

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

const byZscore = (a: DailySignal, b: DailySignal): number => (a.zscore_90 ?? 0) - (b.zscore_90 ?? 0);

export const byStage = (signals: readonly DailySignal[], stage: Stage): readonly DailySignal[] =>
  signals.filter((s) => s.stage === stage).toSorted(byZscore);

export const withAlert = (signals: readonly DailySignal[], alert: Alert): readonly DailySignal[] =>
  signals.filter((s) => s.alert === alert).toSorted(byZscore);

export const allByZscore = (signals: readonly DailySignal[]): readonly DailySignal[] => signals.toSorted(byZscore);

export const historyOf = (history: readonly HistoryPoint[], symbol: string): readonly HistoryPoint[] =>
  history.filter((h) => h.symbol === symbol);

/** Sinal sem vantagem: retorno médio do SINAL abaixo da REFERÊNCIA (compra sem critério). */
export function signalHasEdge(signal: TradeSummary, reference: TradeSummary): boolean | null {
  if (signal.mean === null || reference.mean === null) return null;
  return signal.mean > reference.mean;
}

export const fmt = {
  num: (n: number | null, digits = 2): string => (n === null ? "—" : n.toFixed(digits)),
  pct: (n: number | null, digits = 1): string => (n === null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`),
  price: (n: number | null): string =>
    n === null ? "—" : new Intl.NumberFormat("en-US", { maximumSignificantDigits: 6 }).format(n),
  usd: (n: number | null): string =>
    n === null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n),
  day: (d: Date | null): string => (d === null ? "—" : d.toISOString().slice(0, 10)),
};
