import type { Tone } from "./analytics";
import type {
  DailySignal,
  Decision,
  LabPeriod,
  Opportunity,
  Recommendation,
  Regime,
  SelectionPerf,
  SelectionStrategy,
} from "../types/signals";

/* Funções puras sobre a recomendação já calculada pelo pipeline. Nada aqui calcula aporte, score ou seleção:
   só confere, ordena e traduz o que veio em daily_signals.parquet e recommendation.parquet. */

export const OPPORTUNITY_LABEL: Readonly<Record<Opportunity, { readonly text: string; readonly tone: Tone }>> = {
  BOA_RELATIVA: { text: "Boa oportunidade relativa", tone: "signal" },
  MODERADA: { text: "Oportunidade moderada", tone: "neutral" },
  AGUARDAR: { text: "Aguardar", tone: "warning" },
  EVITAR: { text: "Evitar entrada", tone: "neutral" },
};

export const REGIME_LABEL: Readonly<Record<Regime, { readonly text: string; readonly tone: Tone; readonly note: string }>> = {
  FAVORAVEL: { text: "Favorável", tone: "neutral", note: "Bitcoin acima da média de 200 dias e com a média de 50 dias acima dela" },
  NEUTRO: { text: "Neutro", tone: "neutral", note: "Bitcoin acima da média de 200 dias, mas a média de 50 dias ainda abaixo" },
  DEFENSIVO: { text: "Defensivo", tone: "warning", note: "Bitcoin abaixo da média de 200 dias: a regra de risco não abre compras novas" },
  INDISPONIVEL: { text: "Sem dados confiáveis", tone: "warning", note: "Sem dado confiável do Bitcoin: nenhuma compra é recomendada" },
};

export const DECISION_TEXT: Readonly<Record<Decision, string>> = {
  NAO_INVESTIR: "Não investir nesta análise",
  APORTE_PEQUENO: "Aporte pequeno",
  APORTE_PARCIAL: "Aporte parcial",
  APORTE_AMPLO: "Aporte amplo",
};

export const NO_OPPORTUNITY =
  "Hoje não encontrei oportunidades suficientemente boas dentro dos critérios configurados.";

const BRL0 = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const BRL2 = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** "R$ 45" para inteiros, "R$ 45,50" quando há centavos. */
export const brl = (n: number): string => (Number.isInteger(Math.round(n * 100) / 100) ? BRL0 : BRL2).format(n);

const EPS = 0.005;

/** Invariantes da execução: o painel recusa mostrar uma recomendação que não fecha. */
export function runProblems(signals: readonly DailySignal[], rec: Recommendation): readonly string[] {
  const problems: string[] = [];
  const total = signals.reduce((sum, s) => sum + s.allocation_brl, 0);
  if (signals.some((s) => s.run_ts.getTime() !== rec.run_ts.getTime())) {
    problems.push("daily_signals e recommendation são de execuções diferentes");
  }
  if (signals.some((s) => s.allocation_brl < 0)) problems.push("aporte negativo");
  if (total > rec.budget_brl + EPS) problems.push("soma dos aportes acima do orçamento");
  if (Math.abs(total - rec.total_brl) > EPS) problems.push("total do resumo diferente da soma por moeda");
  if (signals.some((s) => s.allocation_brl > 0 && !s.selected)) problems.push("aporte em moeda não selecionada");
  return problems;
}

const OPPORTUNITY_ORDER: Readonly<Record<Opportunity, number>> = { BOA_RELATIVA: 0, MODERADA: 1, AGUARDAR: 2, EVITAR: 3 };

const byRanking = (a: DailySignal, b: DailySignal): number =>
  OPPORTUNITY_ORDER[a.opportunity] - OPPORTUNITY_ORDER[b.opportunity] || (b.score ?? -1) - (a.score ?? -1) || a.symbol.localeCompare(b.symbol);

/** As moedas selecionadas, na ordem do ranking. */
export const picks = (signals: readonly DailySignal[]): readonly DailySignal[] =>
  signals.filter((s) => s.selected).toSorted((a, b) => (a.candidate_rank ?? 99) - (b.candidate_rank ?? 99));

/** Todas as moedas, da melhor classificação para a pior (empate: score). */
export const ranking = (signals: readonly DailySignal[]): readonly DailySignal[] => signals.toSorted(byRanking);

/** As que não foram selecionadas, com o primeiro bloqueio como motivo principal. */
export const discarded = (signals: readonly DailySignal[]): readonly DailySignal[] => ranking(signals).filter((s) => !s.selected);

export const mainBlocker = (s: DailySignal): string => s.blockers[0] ?? "abaixo das melhores candidatas";

/** O rótulo antes dos dois-pontos ("tendência de alta: preço 12% acima" -> "tendência de alta"). */
export const label = (text: string): string => text.split(":")[0] ?? text;

export interface BudgetSegment {
  readonly key: string;
  readonly label: string;
  readonly amount: number;
  readonly pct: number;
}

/** Fatias do orçamento para a barra: uma por moeda com aporte e o saldo não alocado. */
export function budgetSegments(signals: readonly DailySignal[], rec: Recommendation): readonly BudgetSegment[] {
  if (rec.budget_brl <= 0) return [];
  const pct = (x: number): number => (x / rec.budget_brl) * 100;
  return [
    ...picks(signals)
      .filter((s) => s.allocation_brl > 0)
      .map((s) => ({ key: s.symbol, label: s.symbol.replace("/USDT", ""), amount: s.allocation_brl, pct: pct(s.allocation_brl) })),
    { key: "livre", label: "Não alocado", amount: rec.unallocated_brl, pct: pct(rec.unallocated_brl) },
  ];
}

export const SELECTION_STRATEGY_NAME: Readonly<Record<SelectionStrategy, string>> = {
  SELECAO: "Seleção com aporte variável (a recomendação do painel)",
  SELECAO_PESO_IGUAL: "Seleção com valor igual por moeda",
  MOMENTO_SIMPLES: "Momento simples (as que mais subiram em 90 dias)",
  TENDENCIA_SMA200: "Regra SMA 200 em todas as moedas",
  COMPRAR_E_SEGURAR: "Comprar e segurar todas",
  BTC: "Só Bitcoin",
};

/** Linhas do backtest da seleção num período, na ordem do maior Sharpe para o menor. */
export const selectionRows = (rows: readonly SelectionPerf[], period: LabPeriod): readonly SelectionPerf[] =>
  rows.filter((r) => r.period === period).toSorted((a, b) => (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity));

/** Distância do preço para a média de 200 dias, em %, a partir dos campos da linha. */
export const aboveSma200 = (s: DailySignal): number | null =>
  s.sma_200 === null || s.sma_200 === 0 ? null : (s.close / s.sma_200 - 1) * 100;
