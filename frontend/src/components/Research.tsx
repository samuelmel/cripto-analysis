import { useState } from "react";
import { fmt, fmtRatio, labRows, signTone } from "../data/analytics";
import type { LabPeriod, LabResult, Portfolio } from "../types/signals";
import { Term } from "./Glossary";
import { Block, TEXT_TONE, Table, cell, hideNarrow, numCell } from "./ui";

const PERIOD_TEXT: Readonly<Record<LabPeriod, string>> = {
  TESTE: "Teste (2023 em diante)",
  VALIDACAO: "Validação (2021 e 2022)",
  TREINO: "Treino (2018 a 2020)",
};
const UNIVERSE_TEXT: Readonly<Record<Portfolio, string>> = { PRINCIPAIS: "Bitcoin e Ethereum", TODAS: "Todas as moedas analisadas" };

export function Choice<T extends string>({ label, value, options, onChange }: {
  readonly label: string;
  readonly value: T;
  readonly options: Readonly<Record<T, string>>;
  readonly onChange: (v: T) => void;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="text-[13px] font-medium text-muted">{label}</legend>
      <div className="mt-1 flex flex-wrap gap-2">
        {(Object.keys(options) as T[]).map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={k === value}
            onClick={() => onChange(k)}
            className={`rounded-sm border px-3 py-1.5 text-[14px] transition-colors ${
              k === value ? "border-signal bg-signal-bg font-medium" : "border-hairline bg-surface hover:bg-ground"
            }`}
          >
            {options[k]}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

/** Laboratório de estratégias: tudo aparece, inclusive o que perde. Vem de research/strategy_lab.py. */
export function LabPanel({ rows }: { readonly rows: readonly LabResult[] }) {
  const [universe, setUniverse] = useState<Portfolio>("PRINCIPAIS");
  const [period, setPeriod] = useState<LabPeriod>("TESTE");
  if (rows.length === 0) {
    return (
      <Block>
        <p className="font-medium">O laboratório ainda não rodou.</p>
        <p className="mt-2 text-muted">Para comparar mais estratégias, rode no terminal, na pasta do projeto, e recarregue a página:</p>
        <pre className="mt-3 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[13px]">uv run python research/strategy_lab.py</pre>
      </Block>
    );
  }
  const shown = labRows(rows, universe, period);
  return (
    <>
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Choice label="Carteira" value={universe} options={UNIVERSE_TEXT} onChange={setUniverse} />
        <Choice label="Período" value={period} options={PERIOD_TEXT} onChange={setPeriod} />
      </div>
      <div className="mt-4">
        <Table
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
      </div>
      <p className="mt-3 max-w-[72ch] text-[13px] text-muted">
        <Term id="sharpe">Sharpe</Term> e <Term id="drawdown">pior queda</Term> comparam risco e retorno. "Bate o sorteio" diz em quantos sorteios com a mesma
        exposição e o dia das operações escolhido ao acaso a estratégia rendeu mais. Os parâmetros foram escolhidos na validação; o teste nunca entrou na escolha.
      </p>
    </>
  );
}
