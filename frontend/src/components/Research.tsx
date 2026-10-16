import { useState } from "react";
import { fmt, fmtRatio, labRows, signTone } from "../data/analytics";
import type { LabPeriod, LabResult, Portfolio } from "../types/signals";
import { Term } from "./Glossary";
import { Empty, Segmented, TEXT_TONE, Table, cell, hideNarrow, numCell } from "./ui";

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
