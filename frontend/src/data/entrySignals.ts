/* Sinais de entrada (docs/entry_signals.md): textos, ordenação e candidatas do dia. Funções puras, sem fetch. */
import type { DailySignal, EntryLevel, EntryLevelRow } from "../types/signals";

/** Espelha entry_live.COMBO_TEXT (Python). */
export const COMBO_TEXT: Readonly<Record<string, string>> = {
  A_30: "entre as 5 maiores altas de 30 dias",
  A_60: "entre as 5 maiores altas de 60 dias",
  A_90: "entre as 5 maiores altas de 90 dias",
  B_10: "recuo de 10% em tendência de alta",
  B_15: "recuo de 15% em tendência de alta",
  B_20: "recuo de 20% em tendência de alta",
  C: "rompimento da máxima de 55 dias com volume",
  D_30: "entre as 5 mais fortes contra o BTC em 30 dias",
  D_60: "entre as 5 mais fortes contra o BTC em 60 dias",
  D_90: "entre as 5 mais fortes contra o BTC em 90 dias",
  E: "entre as 5 maiores notas do score de seleção",
  F: "entre as 5 maiores probabilidades do modelo (sombra)",
};

export const comboText = (combo: string): string => COMBO_TEXT[combo] ?? combo;

const LEVEL_ORDER: Readonly<Record<EntryLevel, number>> = { VALIDADO: 0, PROMISSOR: 1, SEM_EVIDENCIA: 2 };

export const LEVEL_LABEL: Readonly<Record<EntryLevel, { readonly text: string; readonly tone: "good" | "warning" | "neutral" }>> = {
  VALIDADO: { text: "Validado", tone: "good" },
  PROMISSOR: { text: "Promissor", tone: "warning" },
  SEM_EVIDENCIA: { text: "Sem evidência", tone: "neutral" },
};

/** Níveis ordenados: validados, promissores, o resto; dentro do nível, na ordem da grade. */
export function sortedLevels(rows: readonly EntryLevelRow[]): readonly EntryLevelRow[] {
  return [...rows].sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level] || a.combo.localeCompare(b.combo));
}

/** Candidatas do dia: moedas com dado confiável na condição de um sinal VALIDADO ou PROMISSOR (validadas primeiro). */
export function entryCandidates(signals: readonly DailySignal[]): readonly DailySignal[] {
  return signals
    .filter((s) => s.entry_level !== null && s.stage !== "INDISPONÍVEL")
    .sort((a, b) => {
      const la = a.entry_level === null ? 3 : LEVEL_ORDER[a.entry_level];
      const lb = b.entry_level === null ? 3 : LEVEL_ORDER[b.entry_level];
      return la - lb || (a.entry_since?.getTime() ?? 0) - (b.entry_since?.getTime() ?? 0) || a.symbol.localeCompare(b.symbol);
    });
}
