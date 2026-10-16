import type { MarketRegime, MarketTrendRegime, MarketVolRegime, RegimeStatus } from "../types/signals";
import type { Tone } from "./analytics";

/* Funções puras sobre market_regimes.parquet (regimes de mercado do BTC, causais e experimentais). Só resumem e
   traduzem o que o pipeline publicou: nenhuma classificação é recalculada aqui. */

export const TREND_TEXT: Readonly<Record<MarketTrendRegime, { readonly text: string; readonly tone: Tone; readonly note: string }>> = {
  ALTA: { text: "Alta", tone: "good", note: "Preço bem acima da média de 200 dias, que não está caindo" },
  BAIXA: { text: "Baixa", tone: "critical", note: "Preço bem abaixo da média de 200 dias, que não está subindo" },
  LATERAL: { text: "Lateral", tone: "neutral", note: "Preço colado numa média plana" },
  MISTO: { text: "Misto", tone: "warning", note: "Sinais conflitantes ou transição" },
  INDETERMINADO: { text: "Indeterminado", tone: "neutral", note: "Dados válidos, mas nenhum estado confirmado ainda" },
  INDISPONIVEL: { text: "Indisponível", tone: "warning", note: "Sem dado confiável para classificar" },
};

export const VOL_TEXT: Readonly<Record<MarketVolRegime, { readonly text: string; readonly tone: Tone }>> = {
  NORMAL: { text: "normal", tone: "neutral" },
  ALTA: { text: "alta", tone: "warning" },
  INDISPONIVEL: { text: "indisponível", tone: "neutral" },
};

export const STATUS_TEXT: Readonly<Record<RegimeStatus, string>> = {
  OK: "Dados válidos",
  SEM_CANDLE: "Dia sem candle",
  DADO_INVALIDO: "Preço inválido no dia",
  HISTORICO_INSUFICIENTE: "Histórico insuficiente (aquecimento)",
  DADOS_INCOMPLETOS: "Janela com muitos buracos",
};

/** Cor da faixa do tempo (classes do Tailwind sobre os tokens do DESIGN.md). */
export const TREND_COLOR: Readonly<Record<MarketTrendRegime, string>> = {
  ALTA: "var(--color-good-mark)",
  BAIXA: "var(--color-critical-mark)",
  LATERAL: "var(--color-neutral-mark)",
  MISTO: "var(--color-warning-mark)",
  INDETERMINADO: "var(--color-hairline)",
  INDISPONIVEL: "var(--color-hairline)",
};

/** A linha do último dia classificado (a última da tabela); null se o arquivo não existe ou está vazio. */
export const latestRegime = (rows: readonly MarketRegime[]): MarketRegime | null => rows.at(-1) ?? null;

export interface RegimeRun<T extends string = MarketTrendRegime> {
  readonly label: T;
  readonly start: Date;
  readonly end: Date;
  readonly days: number;
}

export const VOL_COLOR: Readonly<Record<MarketVolRegime, string>> = {
  NORMAL: "var(--color-hairline)",
  ALTA: "var(--color-warning-mark)",
  INDISPONIVEL: "transparent",
};

const DAY_MS = 86_400_000;

/** Sequências de dias seguidos com o mesmo rótulo, do mais antigo ao mais recente (um buraco no calendário abre outra). */
function runsBy<T extends string>(rows: readonly MarketRegime[], pick: (r: MarketRegime) => T): readonly RegimeRun<T>[] {
  const runs: RegimeRun<T>[] = [];
  for (const r of rows) {
    const label = pick(r);
    const last = runs.at(-1);
    if (last !== undefined && last.label === label && r.timestamp.getTime() - last.end.getTime() === DAY_MS) {
      runs[runs.length - 1] = { ...last, end: r.timestamp, days: last.days + 1 };
    } else {
      runs.push({ label, start: r.timestamp, end: r.timestamp, days: 1 });
    }
  }
  return runs;
}

/** Sequências do regime de tendência. */
export const trendRuns = (rows: readonly MarketRegime[]): readonly RegimeRun[] => runsBy(rows, (r) => r.trend_regime);

/** Sequências do regime de volatilidade. */
export const volRuns = (rows: readonly MarketRegime[]): readonly RegimeRun<MarketVolRegime>[] => runsBy(rows, (r) => r.vol_regime);

export interface RegimeShare {
  readonly label: MarketTrendRegime;
  readonly days: number;
  readonly pct: number;
}

/** Dias em cada regime de tendência, em % dos dias classificados (exclui indisponível e indeterminado do total). */
export function trendShares(rows: readonly MarketRegime[]): readonly RegimeShare[] {
  const counts = new Map<MarketTrendRegime, number>();
  for (const r of rows) counts.set(r.trend_regime, (counts.get(r.trend_regime) ?? 0) + 1);
  const classified = (["ALTA", "BAIXA", "LATERAL", "MISTO"] as const).reduce((sum, k) => sum + (counts.get(k) ?? 0), 0);
  return (["ALTA", "BAIXA", "MISTO", "LATERAL"] as const).map((label) => {
    const days = counts.get(label) ?? 0;
    return { label, days, pct: classified === 0 ? 0 : (days / classified) * 100 };
  });
}

/** Percentual dos dias classificados em volatilidade alta (null se nenhum dia tem a volatilidade classificada). */
export function highVolShare(rows: readonly MarketRegime[]): number | null {
  const classified = rows.filter((r) => r.vol_regime !== "INDISPONIVEL");
  return classified.length === 0 ? null : (classified.filter((r) => r.vol_regime === "ALTA").length / classified.length) * 100;
}

/** Quantas vezes o regime de tendência confirmado trocou entre dias classificados (menos = mais estável). */
export function trendSwitches(rows: readonly MarketRegime[]): number {
  const ok = rows.filter((r) => r.trend_regime !== "INDISPONIVEL" && r.trend_regime !== "INDETERMINADO");
  return ok.reduce((n, r, i) => (i > 0 && ok[i - 1]?.trend_regime !== r.trend_regime ? n + 1 : n), 0);
}
