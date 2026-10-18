/* Tela "Hoje": o resumo do dia em português simples, para quem não conhece o assunto. Funções puras, sem fetch.
   Cada frase sai de um campo que o pipeline publica; nada é calculado de novo aqui. */
import type { Dashboard, DailySignal, Regime, SourceEvent } from "../types/signals";
import { coinName, fmt, fngLabel, signTone, type Tone } from "./analytics";
import { entryCandidates } from "./entrySignals";
import { brl } from "./selection";

export interface Chip {
  readonly label: string;
  readonly value: string;
  readonly hint: string;
  readonly tone: Tone;
}

export interface TodaySummary {
  readonly headline: string;
  readonly lines: readonly string[];
  readonly chips: readonly Chip[];
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;
const capitalize = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

const MARKET_LINE: Readonly<Record<Regime, string>> = {
  FAVORAVEL: "O mercado está favorável: o Bitcoin segue em alta no longo prazo.",
  NEUTRO: "O mercado está neutro: o Bitcoin está em alta no longo prazo, mas perdeu força nas últimas semanas.",
  DEFENSIVO: "O mercado está em queda: o Bitcoin está abaixo da média de 200 dias, e o sistema não sugere compras novas.",
  INDISPONIVEL: "Sem dados confiáveis do Bitcoin hoje: por segurança, nenhuma compra é sugerida.",
};

const MARKET_CHIP: Readonly<Record<Regime, { readonly value: string; readonly tone: Tone }>> = {
  FAVORAVEL: { value: "Favorável", tone: "good" },
  NEUTRO: { value: "Neutro", tone: "neutral" },
  DEFENSIVO: { value: "Em queda", tone: "warning" },
  INDISPONIVEL: { value: "Sem dados", tone: "warning" },
};

export function todaySummary(data: Dashboard): TodaySummary {
  const { recommendation: rec, signals, positions, entryLevels } = data;
  const buy = signals.filter((s) => s.stage === "COMPRAR").map((s) => coinName(s.symbol));
  const watch = entryCandidates(signals).filter((s) => s.stage !== "COMPRAR");

  const headline =
    rec.total_brl > 0
      ? `Considere aplicar ${brl(rec.total_brl)} de ${brl(rec.budget_brl)} em ${plural(rec.n_funded, "moeda", "moedas")}, ou espere.`
      : "Hoje não há aporte sugerido. Pode esperar com tranquilidade.";

  const lines = [MARKET_LINE[rec.regime]];
  if (buy.length > 0) lines.push(`Sinal de compra confirmado pela estatística em ${buy.join(", ")}.`);
  else if (entryLevels.length > 0) {
    lines.push(
      watch.length > 0
        ? `Nenhum sinal de compra confirmado. ${plural(watch.length, "moeda está", "moedas estão")} em observação.`
        : "Nenhum sinal de compra confirmado e nenhuma moeda em observação.",
    );
  }
  lines.push("É uma simulação: o sistema não compra nada nem acessa o seu saldo.");

  const fng = signals[0]?.fng_value ?? null;
  const value = positions.reduce((a, p) => a + (p.value_usd ?? 0), 0);
  const pnl = positions.reduce((a, p) => a + (p.pnl_usd ?? 0), 0);
  const cost = value - pnl;
  const pnlPct = cost > 0 ? (pnl / cost) * 100 : null;

  const chips: Chip[] = [
    { label: "Mercado", ...MARKET_CHIP[rec.regime], hint: MARKET_LINE[rec.regime] },
    {
      label: "Humor do mercado",
      value: fng === null ? "—" : `${capitalize(fngLabel(signals[0]?.fng_classification ?? null))} (${fng})`,
      hint: "Índice de 0 (pânico) a 100 (euforia). Só contexto, não decide nada.",
      tone: "neutral",
    },
    {
      label: "Suas posições",
      value: positions.length === 0 ? "Nenhuma" : `${positions.length} · ${pnlPct === null ? fmt.usd(pnl) : fmt.pct(pnlPct, 1)}`,
      hint: positions.length === 0 ? "Registre uma compra para acompanhar." : `Valor de hoje ${fmt.usd(value)}, resultado ${fmt.usd(pnl)}.`,
      tone: positions.length === 0 ? "neutral" : signTone(pnl),
    },
  ];
  return { headline, lines, chips };
}

export interface SimpleNotice {
  readonly tone: "warning" | "critical";
  readonly text: string;
  readonly detail: string;
}

/** Avisos curtos: moedas sem dado viram uma linha só; falhas de coleta e pânico em frase simples. */
export function simpleNotices(signals: readonly DailySignal[], sources: readonly SourceEvent[], lag: number | null): readonly SimpleNotice[] {
  const out: SimpleNotice[] = [];
  const stale = signals.filter((s) => s.stage === "INDISPONÍVEL");
  if (stale.length > 0) {
    const names = stale.map((s) => coinName(s.symbol));
    out.push({
      tone: "warning",
      text:
        stale.length === signals.length
          ? "Os dados de hoje ainda não chegaram: nenhuma moeda pode ser avaliada agora."
          : `${plural(stale.length, "moeda ficou", "moedas ficaram")} de fora hoje por falta de dados atualizados: ${names.join(", ")}.`,
      detail: stale.map((s) => `${coinName(s.symbol)}: ${s.stage_reason ?? "dado desatualizado"}`).join(" · "),
    });
  } else if (lag !== null && lag > 0) {
    out.push({ tone: "warning", text: `Os dados estão ${plural(lag, "dia", "dias")} atrasados.`, detail: "Os números valem com ressalva." });
  }
  const failed = sources.filter((e) => e.status === "erro");
  if (failed.length > 0) {
    out.push({
      tone: "critical",
      text: `A coleta falhou em ${plural(failed.length, "fonte", "fontes")} na última atualização.`,
      detail: failed.map((e) => `${e.source}: ${e.detail === "" ? "não respondeu" : e.detail}`).join(" · "),
    });
  }
  const panic = signals.filter((s) => s.panic).map((s) => coinName(s.symbol));
  if (panic.length > 0) {
    out.push({
      tone: "warning",
      text: `Queda forte com medo no mercado em ${panic.join(", ")}.`,
      detail: "É só um aviso: comprar no pânico perdeu dinheiro nos testes.",
    });
  }
  return out;
}
