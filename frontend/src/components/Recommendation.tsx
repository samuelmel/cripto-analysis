import { ListMagnifyingGlass } from "@phosphor-icons/react";
import { useState } from "react";
import { coinName, fmt, fmtDateTime, signTone } from "../data/analytics";
import {
  NO_OPPORTUNITY,
  OPPORTUNITY_LABEL,
  SELECTION_STRATEGY_NAME,
  aboveSma200,
  brl,
  budgetSegments,
  discarded,
  label,
  mainBlocker,
  picks,
  ranking,
  selectionRows,
} from "../data/selection";
import type { DailySignal, LabPeriod, Recommendation, SelectionPerf } from "../types/signals";
import { CoinLabel } from "./CoinLabel";
import { Term } from "./Glossary";
import { Badge, Collapsible, Empty, Panel, Segmented, TEXT_TONE, Table, cell, hideNarrow, numCell } from "./ui";

/* Tudo aqui só mostra a recomendação calculada pelo pipeline (daily_signals + recommendation da mesma execução). */

const SEGMENT_SHADE = ["bg-series-price", "bg-series-trend", "bg-series-average"] as const;

/** O orçamento dividido entre as moedas e o que fica sem investir, sempre somando 100%. */
function BudgetBar({ signals, rec }: { readonly signals: readonly DailySignal[]; readonly rec: Recommendation }) {
  const segments = budgetSegments(signals, rec);
  if (segments.length === 0) return null;
  return (
    <div className="mt-2">
      <div aria-hidden className="flex h-2 overflow-hidden rounded-sm bg-ground">
        {segments.map((s, i) =>
          s.key === "livre" ? null : (
            <span key={s.key} className={`${SEGMENT_SHADE[i % SEGMENT_SHADE.length] ?? ""} h-full border-r border-surface`} style={{ width: `${s.pct}%` }} />
          ),
        )}
      </div>
      <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px]">
        {segments.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1">
            <span aria-hidden className={`inline-block h-2 w-2 rounded-sm ${s.key === "livre" ? "bg-ground ring-1 ring-hairline" : SEGMENT_SHADE[i % SEGMENT_SHADE.length] ?? ""}`} />
            <span className="font-medium">{s.label}</span>
            <span className="num text-muted">{brl(s.amount)} ({fmt.num(s.pct, 0)}%)</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const COMPONENTS = [
  { key: "score_momentum", name: "Momento" },
  { key: "score_stability", name: "Persistência" },
  { key: "score_risk", name: "Risco (menor é melhor)" },
  { key: "score_liquidity", name: "Liquidez" },
] as const;

function ScoreParts({ s }: { readonly s: DailySignal }) {
  return (
    <ul className="space-y-1">
      {COMPONENTS.map((c) => {
        const v = s[c.key];
        return (
          <li key={c.key} className="grid grid-cols-[8rem_1fr_2rem] items-center gap-2 text-[12px]">
            <span className="text-muted">{c.name}</span>
            <span aria-hidden className="block h-1.5 rounded-sm bg-ground">
              <span className="block h-full rounded-sm bg-series-price" style={{ width: `${v ?? 0}%` }} />
            </span>
            <span className="num text-right">{v === null ? "—" : fmt.num(v, 0)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Uma moeda selecionada: linha de resumo sempre visível (aporte, score, motivo principal) e o detalhe recolhido. */
function PickItem({ s, index }: { readonly s: DailySignal; readonly index: number }) {
  const opp = OPPORTUNITY_LABEL[s.opportunity];
  const theoretical = s.theoretical_brl > s.allocation_brl + 0.5;
  return (
    <li className="border-b border-hairline last:border-0">
      <details className="group">
        <summary
          aria-label={`Oportunidade ${index}: ${coinName(s.symbol)}`}
          className="grid cursor-pointer list-none grid-cols-[1.25rem_minmax(0,1fr)_auto_auto] items-center gap-x-2 gap-y-0.5 px-3 py-1.5 hover:bg-ground [&::-webkit-details-marker]:hidden"
        >
          <span className="num text-[12px] text-muted">{index}.</span>
          <span className="flex min-w-0 items-center gap-2">
            <CoinLabel symbol={s.symbol} size={20} />
            <Badge tone={opp.tone}>{opp.text}</Badge>
          </span>
          <span className="num text-right text-[15px] font-semibold">{brl(s.allocation_brl)}</span>
          <span className="num w-14 text-right text-[12px] text-muted">{s.score === null ? "—" : `${fmt.num(s.score, 0)}/100`}</span>
          <span className="col-start-2 col-end-5 truncate text-[12px] text-muted">{s.reasons[0] ?? ""}</span>
        </summary>
        <div className="grid gap-3 px-3 pb-2.5 pt-1 text-[12px] md:grid-cols-2">
          <div>
            <p className="mb-1 font-medium text-muted"><Term id="score">Score relativo</Term></p>
            <ScoreParts s={s} />
            {s.allocation_note !== null && <p className="mt-1.5 text-warning">{s.allocation_note}</p>}
            {theoretical && <p className="mt-1.5 text-muted"><Term id="teorica">Alocação teórica</Term> {brl(Math.round(s.theoretical_brl * 100) / 100)}</p>}
          </div>
          <div>
            <p className="font-medium text-muted">Por que</p>
            <ul className="mt-0.5 list-disc space-y-0.5 pl-4">{s.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            <p className="mt-1.5 font-medium text-muted">Principais riscos</p>
            {s.risks.length === 0 ? (
              <p className="mt-0.5">Nenhum alerta além da oscilação normal de cripto.</p>
            ) : (
              <ul className="mt-0.5 list-disc space-y-0.5 pl-4">{s.risks.map((r) => <li key={r}>{r}</li>)}</ul>
            )}
            <dl className="mt-2 grid grid-cols-4 gap-2 border-t border-hairline pt-1.5">
              <div><dt className="text-muted">90 dias</dt><dd className={`num font-medium ${TEXT_TONE[signTone(s.ret_90d_pct)]}`}>{fmt.pct(s.ret_90d_pct)}</dd></div>
              <div><dt className="text-muted"><Term id="volatilidade">Volat.</Term></dt><dd className="num font-medium">{s.vol_90d_pct === null ? "—" : `${fmt.num(s.vol_90d_pct, 0)}%`}</dd></div>
              <div><dt className="text-muted">Preço</dt><dd className="num font-medium">{fmt.price(s.close)}</dd></div>
              <div><dt className="text-muted"><Term id="custo">Custo</Term></dt><dd className="num font-medium">{s.est_cost_pct === null ? "—" : `${fmt.num(s.est_cost_pct, 2)}%`}</dd></div>
            </dl>
          </div>
        </div>
      </details>
    </li>
  );
}

/** Moedas descartadas com o motivo principal; a lista completa e os indicadores ficam na aba Seleção. */
export function DiscardedTable({ signals, maxHeight }: { readonly signals: readonly DailySignal[]; readonly maxHeight?: string }) {
  const rows = discarded(signals);
  return (
    <Table
      flush
      {...(maxHeight === undefined ? {} : { maxHeight })}
      caption="Moedas não selecionadas e o que impede a compra"
      columns={[{ label: "Moeda" }, { label: "Classificação" }, { label: "Score", numeric: true, narrow: "hide" }, { label: "O que impede a compra" }]}
    >
      {rows.map((s) => (
        <tr key={s.symbol} className="border-b border-hairline align-top">
          <td className={cell}><CoinLabel symbol={s.symbol} size={18} /></td>
          <td className={cell}><Badge tone={OPPORTUNITY_LABEL[s.opportunity].tone}>{OPPORTUNITY_LABEL[s.opportunity].text}</Badge></td>
          <td className={`${numCell} ${hideNarrow}`}>{s.score === null ? "—" : fmt.num(s.score, 0)}</td>
          <td className={`${cell} whitespace-normal text-[12px]`}>
            {mainBlocker(s)}
            {s.blockers.length > 1 && <span className="text-muted"> (+{s.blockers.length - 1})</span>}
          </td>
        </tr>
      ))}
    </Table>
  );
}

/** A recomendação do dia: frase de decisão, orçamento e as moedas selecionadas. */
export function RecommendationPanel({ signals, rec, onDetails }: {
  readonly signals: readonly DailySignal[];
  readonly rec: Recommendation;
  readonly onDetails: () => void;
}) {
  const chosen = picks(signals);
  const none = rec.total_brl <= 0;
  return (
    <Panel
      id="recomendacao"
      title="Recomendação de aporte"
      note={`${rec.n_analyzed} analisadas, ${rec.n_candidates} candidatas, ${rec.n_funded} com aporte`}
      actions={
        <button type="button" onClick={onDetails} className="flex items-center gap-1 text-[12px] font-medium text-signal hover:underline">
          <ListMagnifyingGlass size={14} aria-hidden /> Indicadores e backtest
        </button>
      }
      bodyClassName="p-0"
    >
      <div className="px-3 pt-2.5">
        <p className="text-[15px] font-semibold leading-snug">
          {none ? NO_OPPORTUNITY : `Considerar um aporte de ${brl(rec.total_brl)} de ${brl(rec.budget_brl)}, ou aguardar.`}
        </p>
        <p className="mt-0.5 text-[12px] text-muted">
          {none
            ? `Aporte sugerido: R$ 0 de ${brl(rec.budget_brl)}. O orçamento permanece sem alocação.`
            : `${brl(rec.unallocated_brl)} ficam sem investir; a soma nunca passa do orçamento.`}
        </p>
        <BudgetBar signals={signals} rec={rec} />
      </div>
      {chosen.length > 0 && <ul className="mt-2 border-t border-hairline">{chosen.map((s, i) => <PickItem key={s.symbol} s={s} index={i + 1} />)}</ul>}
      <div className="border-t border-hairline px-3 py-2">
        {(rec.notes.length > 0 || rec.data_notes.length > 0) && (
          <ul className="mb-1.5 space-y-0.5 text-[12px]">
            {rec.data_notes.map((n) => <li key={n} className="text-warning">Limitação dos dados: {n}.</li>)}
            {rec.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}
        <Collapsible summary="Validação histórica e como ler a recomendação">
          <p><strong className="font-medium text-ink">Validação histórica:</strong> {rec.evidence}</p>
          <p className="mt-1">
            Os valores são estimativas de dimensionamento do modelo quantitativo, não previsão de preço nem garantia de valorização. A{" "}
            <Term id="classificacao">classificação</Term> compara as moedas entre si e com filtros de risco; não é probabilidade de lucro.
            {rec.excluded.length > 0 && ` Fora da análise: ${rec.excluded.join("; ")}.`}
          </p>
        </Collapsible>
      </div>
    </Panel>
  );
}

const PERIOD_TEXT: Readonly<Record<LabPeriod, string>> = {
  TESTE: "Teste (2023 em diante)",
  VALIDACAO: "Validação (2021–22)",
  TREINO: "Treino (2018–20)",
};

/** Aba Seleção: o ranking completo com os indicadores e o backtest contra as referências simples. */
export function SelectionView({ signals, rec, perf }: {
  readonly signals: readonly DailySignal[];
  readonly rec: Recommendation;
  readonly perf: readonly SelectionPerf[];
}) {
  const [period, setPeriod] = useState<LabPeriod>("TESTE");
  const rows = ranking(signals);
  const shownPerf = selectionRows(perf, period);
  return (
    <div className="grid gap-3 xl:grid-cols-12">
      <Panel
        id="ranking"
        title="Ranking de todas as moedas analisadas"
        note={`componentes em percentil (0 a 100) contra as outras do dia; análise de ${fmtDateTime(rec.run_ts)}`}
        className="xl:col-span-12"
        bodyClassName="p-0"
      >
        <Table
          flush
          maxHeight="max-h-[420px]"
          caption="Ranking da seleção com componentes do score, indicadores e aporte"
          columns={[
            { label: "Moeda" }, { label: "Classificação" }, { label: "Score", numeric: true },
            { label: "Momento", numeric: true, narrow: "hide" }, { label: "Persist.", numeric: true, narrow: "hide" },
            { label: "Risco", numeric: true, narrow: "hide" }, { label: "Liquidez", numeric: true, narrow: "hide" },
            { label: "30 d", numeric: true, narrow: "hide" }, { label: "90 d", numeric: true, narrow: "hide" },
            { label: "Vs. média 200", numeric: true, narrow: "hide" }, { label: "Volat.", numeric: true, narrow: "hide" },
            { label: "Condições", numeric: true, narrow: "hide" }, { label: "Aporte", numeric: true },
            { label: "Motivo principal", narrow: "hide" },
          ]}
        >
          {rows.map((s) => (
            <tr key={s.symbol} className="border-b border-hairline">
              <td className={cell}><CoinLabel symbol={s.symbol} size={18} /></td>
              <td className={cell}><Badge tone={OPPORTUNITY_LABEL[s.opportunity].tone}>{OPPORTUNITY_LABEL[s.opportunity].text}</Badge></td>
              <td className={numCell}>{s.score === null ? "—" : fmt.num(s.score, 0)}</td>
              <td className={`${numCell} ${hideNarrow}`}>{s.score_momentum === null ? "—" : fmt.num(s.score_momentum, 0)}</td>
              <td className={`${numCell} ${hideNarrow}`}>{s.score_stability === null ? "—" : fmt.num(s.score_stability, 0)}</td>
              <td className={`${numCell} ${hideNarrow}`}>{s.score_risk === null ? "—" : fmt.num(s.score_risk, 0)}</td>
              <td className={`${numCell} ${hideNarrow}`}>{s.score_liquidity === null ? "—" : fmt.num(s.score_liquidity, 0)}</td>
              <td className={`${numCell} ${hideNarrow} ${TEXT_TONE[signTone(s.ret_30d_pct)]}`}>{fmt.pct(s.ret_30d_pct, 0)}</td>
              <td className={`${numCell} ${hideNarrow} ${TEXT_TONE[signTone(s.ret_90d_pct)]}`}>{fmt.pct(s.ret_90d_pct, 0)}</td>
              <td className={`${numCell} ${hideNarrow}`}>{fmt.pct(aboveSma200(s), 0)}</td>
              <td className={`${numCell} ${hideNarrow}`}>{s.vol_90d_pct === null ? "—" : `${fmt.num(s.vol_90d_pct, 0)}%`}</td>
              <td className={`${numCell} ${hideNarrow}`}>{s.conditions_met} de {s.conditions_total}</td>
              <td className={numCell}>{brl(s.allocation_brl)}</td>
              <td className={`${cell} ${hideNarrow} max-w-[34ch] truncate text-[12px] text-muted`} title={s.selected ? s.reasons[0] ?? "" : mainBlocker(s)}>
                {s.selected ? label(s.reasons[0] ?? "") : mainBlocker(s)}
              </td>
            </tr>
          ))}
        </Table>
      </Panel>

      <Panel
        id="bt-selecao"
        title="A seleção funciona no passado?"
        note={`refeita a cada 7 dias com ${brl(rec.budget_brl)}; taxa de 0,1% por lado, spread e slippage estimados`}
        className="xl:col-span-8"
        actions={perf.length === 0 ? undefined : <Segmented label="Período" value={period} options={PERIOD_TEXT} onChange={setPeriod} />}
        bodyClassName="p-0"
      >
        <p className="px-3 py-2 text-[13px]">{rec.evidence}</p>
        {perf.length === 0 ? (
          <div className="px-3 pb-2"><Empty title="O backtest da seleção ainda não foi publicado">Rode o pipeline.</Empty></div>
        ) : (
          <Table
            flush
            caption={`Backtest da seleção contra as referências, período ${PERIOD_TEXT[period]}, ordenado pelo Sharpe`}
            columns={[
              { label: "Estratégia" }, { label: "Retorno total", numeric: true }, { label: "Por ano", numeric: true, narrow: "hide" },
              { label: "Pior queda", numeric: true }, { label: "Sharpe", numeric: true }, { label: "Comprado", numeric: true, narrow: "hide" },
              { label: "Giro/ano", numeric: true, narrow: "hide" }, { label: "Custos", numeric: true, narrow: "hide" },
            ]}
          >
            {shownPerf.map((r) => (
              <tr key={r.strategy} className="border-t border-hairline">
                <td className={`${cell} ${r.strategy === "SELECAO" ? "font-medium" : ""} whitespace-normal`}>{SELECTION_STRATEGY_NAME[r.strategy]}</td>
                <td className={`${numCell} ${TEXT_TONE[signTone(r.total_return_pct)]}`}>{fmt.pct(r.total_return_pct, 0)}</td>
                <td className={`${numCell} ${hideNarrow}`}>{fmt.pct(r.annual_return_pct)}</td>
                <td className={`${numCell} text-critical`}>{fmt.pct(r.max_drawdown_pct, 0)}</td>
                <td className={numCell}>{r.sharpe === null ? "—" : fmt.num(r.sharpe, 2)}</td>
                <td className={`${numCell} ${hideNarrow}`}>{r.invested_pct === null ? "—" : `${fmt.num(r.invested_pct, 0)}%`}</td>
                <td className={`${numCell} ${hideNarrow}`}>{r.turnover_per_year === null ? "—" : fmt.num(r.turnover_per_year, 1)}</td>
                <td className={`${numCell} ${hideNarrow}`}>{r.cost_pct === null ? "—" : `${fmt.num(r.cost_pct, 1)}%`}</td>
              </tr>
            ))}
          </Table>
        )}
        <p className="border-t border-hairline px-3 py-2 text-[12px] text-muted">
          Limites: só entram moedas que existem hoje (as que quebraram não aparecem, o que favorece comprar altcoins); spread e slippage são
          estimados; execução no fechamento; sem impostos; o período de teste já foi consultado antes (não é prospectivo). O estudo completo
          é gerado por research/selection_study.py.
        </p>
      </Panel>

      <Panel id="metodo" title="Como a seleção decide" className="xl:col-span-4" bodyClassName="space-y-2.5 p-3 text-[12px]">
        <div>
          <h3 className="text-[13px] font-medium">1. Filtros obrigatórios</h3>
          <p className="mt-0.5 text-muted">
            Sem dado recente ou com histórico curto, com <Term id="liquidez">liquidez</Term> baixa, volatilidade ou queda excessiva, ou abaixo da média de 200
            dias: evitar entrada. Com o Bitcoin abaixo da média dele (mercado defensivo), nenhuma compra nova, por mais alto que seja o score.
          </p>
        </div>
        <div>
          <h3 className="text-[13px] font-medium">2. Score e classificação</h3>
          <p className="mt-0.5 text-muted">
            <Term id="momento">Momento</Term>, <Term id="persistencia">persistência</Term>, risco e liquidez viram percentis e somam o{" "}
            <Term id="score">score</Term>. Precisa também de várias condições favoráveis ao mesmo tempo e de preço não esticado. Nenhum sinal
            isolado autoriza compra.
          </p>
        </div>
        <div>
          <h3 className="text-[13px] font-medium">3. Quanto aportar</h3>
          <p className="mt-0.5 text-muted">
            Fração-alvo = risco-alvo ÷ volatilidade da moeda, com limite por moeda, metade para oportunidade moderada e corte pelo orçamento.
            Valores arredondados para baixo; abaixo da ordem mínima ou com custo alto, zero.
          </p>
        </div>
      </Panel>
    </div>
  );
}
