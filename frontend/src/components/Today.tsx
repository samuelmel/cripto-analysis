import { CheckCircle, Info, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";
import { coinName, fmt } from "../data/analytics";
import { RECOMMENDED_SYMBOLS, coinFullName } from "../data/coins";
import { comboText, entryCandidates } from "../data/entrySignals";
import { brl } from "../data/selection";
import type { SimpleNotice, TodaySummary } from "../data/today";
import type { ClosedPosition, DailySignal, Forecast, HistoryPoint, Position, PositionStateRow, Recommendation, Trade } from "../types/signals";
import { CoinLogo } from "./CoinLabel";
import { PositionsSection } from "./Positions";
import { PriceChart } from "./PriceChart";
import { MarketTable } from "./Sections";
import { Empty, Panel, TEXT_TONE } from "./ui";

const day = (d: Date | null): string =>
  d === null ? "—" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "UTC" });

/** Resumo do dia: uma frase do que fazer, o porquê em linguagem simples e três indicadores. */
function TodayHero({ summary }: { readonly summary: TodaySummary }) {
  return (
    <section aria-labelledby="hoje-titulo" className="rounded-md border border-hairline bg-surface p-4 sm:p-5">
      <p className="text-[12px] font-medium uppercase tracking-wide text-muted">Resumo de hoje</p>
      <h2 id="hoje-titulo" className="mt-1 text-[20px] font-semibold leading-snug text-ink sm:text-[22px]">{summary.headline}</h2>
      <ul className="mt-2 space-y-0.5 text-[14px] text-muted">
        {summary.lines.map((l) => <li key={l}>{l}</li>)}
      </ul>
      <dl className="mt-4 grid grid-cols-1 gap-px overflow-hidden rounded-md border border-hairline bg-hairline sm:grid-cols-3">
        {summary.chips.map((c) => (
          <div key={c.label} className="bg-surface px-3 py-2" title={c.hint}>
            <dt className="text-[12px] text-muted">{c.label}</dt>
            <dd className={`text-[15px] font-semibold ${TEXT_TONE[c.tone]}`}>{c.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Avisos em uma frase cada; o detalhe técnico fica recolhido. Sem avisos, uma linha tranquila. */
function Notices({ items }: { readonly items: readonly SimpleNotice[] }) {
  if (items.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-[13px] text-muted">
        <CheckCircle size={16} className="text-good" aria-hidden /> Dados em dia e nenhum aviso.
      </p>
    );
  }
  return (
    <ul aria-label="Avisos" className="space-y-1">
      {items.map((n) => (
        <li key={n.text} className="rounded-md border border-hairline bg-surface px-3 py-2 text-[13px]">
          <details>
            <summary className="flex cursor-pointer list-none items-start gap-2">
              <WarningCircle size={16} className={`mt-0.5 shrink-0 ${n.tone === "critical" ? "text-critical" : "text-warning"}`} aria-hidden />
              <span className="min-w-0">
                <span className="text-ink">{n.text}</span> <span className="text-signal underline-offset-2 hover:underline">detalhes</span>
              </span>
            </summary>
            <p className="mt-1 break-words pl-6 text-[12px] text-muted">{n.detail}</p>
          </details>
        </li>
      ))}
    </ul>
  );
}

/** Onde aplicar: só as moedas com aporte, com o valor e a nota, sem jargão. */
function FundingCard({ signals, rec, onDetails }: {
  readonly signals: readonly DailySignal[];
  readonly rec: Recommendation;
  readonly onDetails: () => void;
}) {
  const funded = signals.filter((s) => s.allocation_brl > 0).toSorted((a, b) => (a.candidate_rank ?? 99) - (b.candidate_rank ?? 99));
  return (
    <Panel id="aplicar" title="Onde aplicar" note="sugestão da seleção" bodyClassName="p-3">
      {funded.length === 0 ? (
        <p className="text-[14px] text-muted">Nenhuma moeda passou em todos os critérios hoje. O orçamento fica guardado.</p>
      ) : (
        <ul className="space-y-2">
          {funded.map((s) => (
            <li key={s.symbol} className="flex items-center gap-3">
              <CoinLogo symbol={s.symbol} size={28} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-ink">{coinFullName(s.symbol)}</span>
                <span className="block text-[12px] text-muted">nota {fmt.num(s.score, 0)} de 100</span>
              </span>
              <span className="num text-[16px] font-semibold text-ink">{brl(s.allocation_brl)}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[12px] text-muted">
        {rec.unallocated_brl > 0 && <>{brl(rec.unallocated_brl)} ficam sem investir. </>}
        A nota compara as moedas entre si; não é chance de lucro.
      </p>
      <button type="button" onClick={onDetails} className="mt-2 text-[13px] font-medium text-signal hover:underline">
        Por que essas moedas? →
      </button>
    </Panel>
  );
}

/** Em observação: candidatas dos sinais de entrada. Explica que ainda não é compra. */
function WatchCard({ signals, hasLevels }: { readonly signals: readonly DailySignal[]; readonly hasLevels: boolean }) {
  const cands = entryCandidates(signals);
  const combos = [...new Set(cands.flatMap((s) => s.entry_combos))];
  return (
    <Panel id="observacao" title="Em observação" note="ainda não é sinal de compra" bodyClassName="p-3">
      {!hasLevels ? (
        <p className="text-[14px] text-muted">A análise dos sinais de entrada ainda não foi publicada.</p>
      ) : cands.length === 0 ? (
        <p className="text-[14px] text-muted">Nenhuma moeda em observação hoje.</p>
      ) : (
        <>
          <ul className="space-y-2">
            {cands.map((s) => (
              <li key={s.symbol} className="flex items-center gap-3">
                <CoinLogo symbol={s.symbol} size={28} />
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-ink">{coinFullName(s.symbol)}</span>
                  <span className="block text-[12px] text-muted">
                    desde {day(s.entry_since)}
                    {s.entry_new ? " · entrou hoje" : ""}
                  </span>
                </span>
                <span className={`text-[12px] font-medium ${s.stage === "COMPRAR" ? "text-good" : "text-warning"}`}>
                  {s.stage === "COMPRAR" ? "Comprar" : "Observar"}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 flex gap-1.5 text-[12px] text-muted">
            <Info size={14} className="mt-0.5 shrink-0" aria-hidden />
            <span>
              Por quê: {combos.map(comboText).join("; ")}. Nos testes isso foi um pouco melhor que a média, mas sem confirmação estatística.
            </span>
          </p>
        </>
      )}
    </Panel>
  );
}

/** Tela "Hoje": resumo, avisos, três cartões e, recolhidos, o gráfico e a lista de todas as moedas. */
export function TodayView(props: {
  readonly summary: TodaySummary;
  readonly notices: readonly SimpleNotice[];
  readonly signals: readonly DailySignal[];
  readonly recommendation: Recommendation;
  readonly hasLevels: boolean;
  readonly selected: string;
  readonly onSelect: (symbol: string) => void;
  readonly coinsByName: readonly DailySignal[];
  readonly sparks: ReadonlyMap<string, readonly number[]>;
  readonly chartHistory: readonly HistoryPoint[];
  readonly chartTrades: readonly Trade[];
  readonly chartPositions: readonly Position[];
  readonly chartForecast: readonly Forecast[];
  readonly positions: readonly Position[];
  readonly closed: readonly ClosedPosition[];
  readonly positionStates: readonly PositionStateRow[];
  readonly onDetails: () => void;
  readonly onChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const { selected } = props;
  return (
    <div className="space-y-3">
      <TodayHero summary={props.summary} />
      <Notices items={props.notices} />
      <div className="grid grid-cols-1 items-start gap-3 md:grid-cols-2 xl:grid-cols-3">
        <FundingCard signals={props.signals} rec={props.recommendation} onDetails={props.onDetails} />
        <WatchCard signals={props.signals} hasLevels={props.hasLevels} />
        <Panel id="posicoes" title="Suas posições" note="o que você já comprou" className="md:col-span-2 xl:col-span-1" bodyClassName="scroll-thin max-h-[420px] overflow-auto p-3">
          <PositionsSection positions={props.positions} closed={props.closed} states={props.positionStates} coins={props.coinsByName} onChanged={props.onChanged} />
        </Panel>
      </div>

      <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)} className="rounded-md border border-hairline bg-surface">
        <summary className="cursor-pointer select-none px-3 py-2.5 text-[14px] font-medium text-ink hover:bg-ground">
          Ver gráfico e todas as moedas
        </summary>
        {open && (
          <div className="grid grid-cols-1 gap-3 border-t border-hairline p-3 lg:grid-cols-12">
            <div className="min-w-0 lg:col-span-7">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <CoinLogo symbol={selected} size={18} />
                <span className="font-medium">{coinFullName(selected)} ({coinName(selected)})</span>
                <select
                  aria-label="Moeda do gráfico"
                  value={selected}
                  onChange={(e) => props.onSelect(e.target.value)}
                  className="ml-auto rounded-sm border border-hairline bg-surface px-2 py-0.5 text-[12px]"
                >
                  {props.coinsByName.map((s) => <option key={s.symbol} value={s.symbol}>{coinName(s.symbol)}</option>)}
                </select>
              </div>
              {props.chartHistory.length === 0 ? (
                <Empty title="Sem histórico de preço para esta moeda" />
              ) : (
                <PriceChart
                  history={props.chartHistory}
                  trades={props.chartTrades}
                  positions={props.chartPositions}
                  forecast={props.chartForecast}
                  showForecast={false}
                  height={280}
                />
              )}
            </div>
            <div className="min-w-0 lg:col-span-5">
              <MarketTable
                rows={props.signals}
                recommended={RECOMMENDED_SYMBOLS}
                sparks={props.sparks}
                selected={selected}
                onSelect={props.onSelect}
                maxHeight="max-h-[340px]"
              />
            </div>
          </div>
        )}
      </details>
    </div>
  );
}
