import { fmt, signTone } from "../data/analytics";
import { LEVEL_LABEL, comboText, entryCandidates, sortedLevels } from "../data/entrySignals";
import type { DailySignal, EntryLevelRow } from "../types/signals";
import { Badge, Empty, TEXT_TONE, Table, cell, hideNarrow, numCell } from "./ui";

const pp = (v: number | null): string => (v === null ? "—" : `${v >= 0 ? "+" : "−"}${fmt.num(Math.abs(v) * 100, 1)} pp`);
const ci = (lo: number | null, hi: number | null): string => (lo === null || hi === null ? "" : `${pp(lo)} a ${pp(hi)}`);
const day = (d: Date | null): string =>
  d === null ? "—" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "UTC" });

/** Sinais de entrada: candidatas de hoje e o nível de cada combinação no estudo agregado (todas aparecem, inclusive as nulas). */
export function EntrySignalsPanel({ levels, signals }: { readonly levels: readonly EntryLevelRow[]; readonly signals: readonly DailySignal[] }) {
  if (levels.length === 0) {
    return (
      <Empty title="Os níveis dos sinais de entrada ainda não foram publicados." tone="warning">
        Sem esse arquivo nenhum sinal conta e nenhuma moeda mostra COMPRAR (falha fechada). Para gerar, rode no terminal e recarregue:
        <pre className="mt-2 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[12px] text-ink">uv run python research/entry_signal_study.py</pre>
      </Empty>
    );
  }
  const candidates = entryCandidates(signals);
  const validated = levels.some((r) => r.level === "VALIDADO");
  return (
    <>
      <div className="border-b border-hairline px-3 py-2 text-[13px]">
        <p className="font-medium text-ink">
          {validated ? "Há sinal VALIDADO: COMPRAR aparece para moedas na condição dele." : "Nenhum sinal VALIDADO: nenhuma moeda mostra COMPRAR."}
        </p>
        {candidates.length === 0 ? (
          <p className="text-muted">Nenhuma moeda com dado confiável está hoje na condição de um sinal validado ou promissor.</p>
        ) : (
          <ul className="mt-1 space-y-0.5">
            {candidates.map((s) => (
              <li key={s.symbol}>
                <strong className="font-medium text-ink">{s.symbol.replace("/USDT", "")}</strong>{" "}
                {s.stage === "COMPRAR" ? "COMPRAR" : "em observação"} · {s.entry_combos.join(", ")} · desde {day(s.entry_since)}
                {s.entry_new ? " (novo hoje)" : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Table
        flush
        maxHeight="max-h-[440px]"
        caption="Nível de cada combinação: excesso de retorno líquido médio (IC 95%) no desenvolvimento e média no teste final"
        columns={[
          { label: "Sinal" },
          { label: "Nível" },
          { label: "Excesso 7d", numeric: true },
          { label: "IC 95% 7d", numeric: true, narrow: "hide" },
          { label: "Excesso 30d", numeric: true },
          { label: "IC 95% 30d", numeric: true, narrow: "hide" },
          { label: "Teste final 7d / 30d", numeric: true, narrow: "hide" },
        ]}
      >
        {sortedLevels(levels).map((r) => (
          <tr key={r.combo} className="border-b border-hairline">
            <td className={cell}>
              <span className="font-medium text-ink">{r.combo}</span> <span className="text-muted">{comboText(r.combo)}</span>
            </td>
            <td className={cell}>
              <Badge tone={LEVEL_LABEL[r.level].tone}>{LEVEL_LABEL[r.level].text}</Badge>
              {r.dev_level !== r.level && <span className="ml-1 text-[12px] text-muted">(era {LEVEL_LABEL[r.dev_level].text.toLowerCase()})</span>}
            </td>
            <td className={`${numCell} ${TEXT_TONE[signTone(r.excess_7)]}`}>{pp(r.excess_7)}</td>
            <td className={`${numCell} ${hideNarrow} text-muted`}>{ci(r.ci_low_7, r.ci_high_7)}</td>
            <td className={`${numCell} ${TEXT_TONE[signTone(r.excess_30)]}`}>{pp(r.excess_30)}</td>
            <td className={`${numCell} ${hideNarrow} text-muted`}>{ci(r.ci_low_30, r.ci_high_30)}</td>
            <td className={`${numCell} ${hideNarrow}`}>
              {r.holdout_excess_7 === null ? "—" : `${pp(r.holdout_excess_7)} / ${pp(r.holdout_excess_30)}`}
            </td>
          </tr>
        ))}
      </Table>
      <p className="border-t border-hairline px-3 py-2 text-[12px] text-muted">
        Excesso: contra a média do universo no mesmo dia (sinais de seleção A, D, E, F) ou contra entrar em dia qualquer da mesma moeda (B, C), com entrada e
        saída na abertura e custos. Validado exige os dois horizontes com correção de Holm sobre 24 hipóteses. Promissor tem excesso positivo sem significância
        e pode ser só a melhor de várias combinações testadas: é observação, não compra. O teste final (desde 2025) só rebaixa. Não é recomendação de compra.
      </p>
    </>
  );
}
