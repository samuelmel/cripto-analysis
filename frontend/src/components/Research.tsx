import { useState } from "react";
import { fmt, fmtRatio, labRows, signTone } from "../data/analytics";
import type { EvidenceStatus, LabPeriod, LabResult, Portfolio, SignalEvidence } from "../types/signals";
import { Term } from "./Glossary";
import { Badge, Empty, Segmented, TEXT_TONE, Table, cell, hideNarrow, numCell } from "./ui";

const PERIOD_TEXT: Readonly<Record<LabPeriod, string>> = {
  TESTE: "Teste (2023+)",
  VALIDACAO: "Validação (2021–22)",
  TREINO: "Treino (2018–20)",
};
const UNIVERSE_TEXT: Readonly<Record<Portfolio, string>> = { PRINCIPAIS: "BTC e ETH", TODAS: "Todas as moedas" };

/** Laboratório de estratégias: tudo aparece, inclusive o que perde. Vem de research/strategy_lab.py. */
export function LabPanel({ rows }: { readonly rows: readonly LabResult[] }) {
  const [universe, setUniverse] = useState<Portfolio>("PRINCIPAIS");
  const [period, setPeriod] = useState<LabPeriod>("TESTE");
  if (rows.length === 0) {
    return (
      <Empty title="O laboratório ainda não rodou.">
        Para comparar mais estratégias, rode no terminal, na pasta do projeto, e recarregue a página:
        <pre className="mt-2 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[12px] text-ink">uv run python research/strategy_lab.py</pre>
      </Empty>
    );
  }
  const shown = labRows(rows, universe, period);
  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-hairline px-3 py-2">
        <Segmented label="Carteira" value={universe} options={UNIVERSE_TEXT} onChange={setUniverse} />
        <Segmented label="Período" value={period} options={PERIOD_TEXT} onChange={setPeriod} />
      </div>
      <Table
        flush
        maxHeight="max-h-[380px]"
        caption={`Estratégias na carteira ${UNIVERSE_TEXT[universe]}, período ${PERIOD_TEXT[period]}, ordenadas pelo Sharpe`}
        columns={[
          { label: "Estratégia" },
          { label: "Parâmetros", narrow: "hide" },
          { label: "Retorno total", numeric: true },
          { label: "Por ano", numeric: true, narrow: "hide" },
          { label: "Pior queda", numeric: true },
          { label: "Sharpe", numeric: true },
          { label: "Operações", numeric: true, narrow: "hide" },
          { label: "Acerto", numeric: true, narrow: "hide" },
          { label: "Bate o sorteio", numeric: true, narrow: "hide" },
        ]}
      >
        {shown.map((r) => (
          <tr key={`${r.strategy}:${r.params}`} className="border-b border-hairline">
            <td className={cell}>{r.strategy.replace(/^\d /, "")}</td>
            <td className={`${cell} ${hideNarrow} text-muted`}>{r.params === "" ? "fixa" : r.params}</td>
            <td className={`${numCell} ${TEXT_TONE[signTone(r.total_return_pct)]}`}>{fmt.pct(r.total_return_pct, 0)}</td>
            <td className={`${numCell} ${hideNarrow} ${TEXT_TONE[signTone(r.annual_return_pct)]}`}>{fmt.pct(r.annual_return_pct)}</td>
            <td className={`${numCell} text-critical`}>{fmt.pct(r.max_drawdown_pct, 0)}</td>
            <td className={numCell}>{fmtRatio(r.sharpe)}</td>
            <td className={`${numCell} ${hideNarrow}`}>{r.n_trades === null ? "—" : fmt.num(r.n_trades, 0)}</td>
            <td className={`${numCell} ${hideNarrow}`}>{r.win_rate_pct === null ? "—" : `${fmt.num(r.win_rate_pct, 0)}%`}</td>
            <td className={`${numCell} ${hideNarrow}`}>{r.beats_random_pct === null ? "—" : `${fmt.num(r.beats_random_pct, 0)}%`}</td>
          </tr>
        ))}
      </Table>
      <p className="border-t border-hairline px-3 py-2 text-[12px] text-muted">
        <Term id="sharpe">Sharpe</Term> e <Term id="drawdown">pior queda</Term> comparam risco e retorno. "Bate o sorteio" diz em quantos sorteios com a mesma
        exposição e o dia das operações escolhido ao acaso a estratégia rendeu mais. Os parâmetros foram escolhidos na validação; o teste nunca entrou na escolha.
      </p>
    </>
  );
}

const EVIDENCE_TEXT: Readonly<Record<EvidenceStatus, string>> = {
  VALIDADA: "Validada",
  NAO_VALIDADA: "Não validada",
  SEM_EVIDENCIA: "Sem evidência",
  REVOGADA: "Revogada no teste final",
  NAO_AVALIADA: "Não avaliada",
};
const EVIDENCE_ORDER: Readonly<Record<EvidenceStatus, number>> = { VALIDADA: 0, REVOGADA: 1, NAO_VALIDADA: 2, SEM_EVIDENCIA: 3, NAO_AVALIADA: 4 };

/** Evidência estatística do COMPRAR por moeda. Só moedas "Validada" mostram COMPRAR no painel e no Telegram. */
export function EvidencePanel({ rows }: { readonly rows: readonly SignalEvidence[] }) {
  if (rows.length === 0) {
    return (
      <Empty title="A validação do COMPRAR ainda não foi publicada." tone="warning">
        Sem esse arquivo nenhuma moeda mostra COMPRAR (o painel falha fechado). Para gerar, rode no terminal e recarregue:
        <pre className="mt-2 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[12px] text-ink">uv run python research/signal_evidence_study.py run</pre>
      </Empty>
    );
  }
  const shown = [...rows].sort((a, b) => EVIDENCE_ORDER[a.status] - EVIDENCE_ORDER[b.status] || a.symbol.localeCompare(b.symbol));
  const pct = (v: number | null) => (v === null ? "—" : fmt.pct(v * 100, 1));
  return (
    <>
      <Table
        flush
        maxHeight="max-h-[420px]"
        caption="Evidência do sinal COMPRAR por moeda: excesso de retorno líquido contra entrar em dia aleatório, em 7 e 30 dias"
        columns={[
          { label: "Moeda" },
          { label: "Situação" },
          { label: "Sinais 7d / 30d", numeric: true, narrow: "hide" },
          { label: "Excesso 7d", numeric: true },
          { label: "Excesso 30d", numeric: true },
          { label: "Teste final", narrow: "hide" },
        ]}
      >
        {shown.map((r) => (
          <tr key={r.symbol} className="border-b border-hairline">
            <td className={cell}>{r.symbol.replace("/USDT", "")}</td>
            <td className={cell}>
              <Badge tone={r.status === "VALIDADA" ? "good" : r.status === "REVOGADA" ? "critical" : "neutral"}>{EVIDENCE_TEXT[r.status]}</Badge>
            </td>
            <td className={`${numCell} ${hideNarrow}`}>
              {r.n_independent_7 ?? "—"} / {r.n_independent_30 ?? "—"}
            </td>
            <td className={`${numCell} ${TEXT_TONE[signTone(r.excess_7)]}`}>{pct(r.excess_7)}</td>
            <td className={`${numCell} ${TEXT_TONE[signTone(r.excess_30)]}`}>{pct(r.excess_30)}</td>
            <td className={`${cell} ${hideNarrow} text-muted`}>{r.holdout === "NAO_APLICA" ? "—" : r.holdout.toLowerCase()}</td>
          </tr>
        ))}
      </Table>
      <p className="border-t border-hairline px-3 py-2 text-[12px] text-muted">
        Excesso = retorno líquido médio após o sinal (entrada no fechamento seguinte, com custos) menos o de entrar em qualquer dia da mesma moeda. Validada exige
        os dois horizontes, valor-p com correção de Holm abaixo de 0,05 e um mínimo de sinais independentes. O teste final (desde 2025) só pode revogar. Moedas
        com poucos sinais ficam sem evidência. Não é recomendação de compra.
      </p>
    </>
  );
}
