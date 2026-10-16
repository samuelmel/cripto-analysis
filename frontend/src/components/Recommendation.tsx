import { Info, ListMagnifyingGlass, Wallet } from "@phosphor-icons/react";
import { useState } from "react";
import { coinName, dataLagDays, fmt, fmtDateTime, signTone } from "../data/analytics";
import {
  DECISION_TEXT,
  NO_OPPORTUNITY,
  OPPORTUNITY_LABEL,
  REGIME_LABEL,
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
import { Choice } from "./Research";
import { Badge, Block, TEXT_TONE, Table, cell, hideNarrow, numCell } from "./ui";

/* Tudo aqui só mostra a recomendação calculada pelo pipeline (daily_signals + recommendation da mesma execução). */

function Fact({ label: name, value, note, tone = "neutral" }: {
  readonly label: React.ReactNode;
  readonly value: string;
  readonly note: React.ReactNode;
  readonly tone?: "neutral" | "warning" | "signal" | "critical" | "good";
}) {
  return (
    <div className="md:px-5 md:first:pl-0 md:last:pr-0">
      <p className="text-[13px] text-muted">{name}</p>
      <p className={`num mt-1 text-lg font-semibold ${TEXT_TONE[tone]}`}>{value}</p>
      <p className="mt-0.5 text-[13px] text-muted">{note}</p>
    </div>
  );
}

/** Faixa de cinco fatos lado a lado no desktop: mercado, orçamento, sugerido, não alocado e dados. */
export function RecommendationStrip({ rec, now }: { readonly rec: Recommendation; readonly now: Date }) {
  const regime = REGIME_LABEL[rec.regime];
  const lag = dataLagDays(rec.data_day, now);
  const fresh = lag === null ? "Sem candles" : lag <= 0 ? "Em dia" : `${lag} ${lag === 1 ? "dia" : "dias"} de atraso`;
  const dataTone = rec.data_status === "OK" && lag !== null && lag <= 0 ? "neutral" : "warning";
  return (
    <Block>
      <div className="grid gap-5 sm:grid-cols-2 md:grid-cols-5 md:gap-0 md:divide-x md:divide-hairline">
        <Fact label={<Term id="regime">Estado do mercado</Term>} value={regime.text} tone={regime.tone} note={regime.note} />
        <Fact label="Orçamento da simulação" value={brl(rec.budget_brl)} note="Valor informado, não é o seu saldo real" />
        <Fact label={<Term id="aporte">Aporte sugerido</Term>} value={brl(rec.total_brl)} note={DECISION_TEXT[rec.decision]} />
        <Fact label="Fica sem investir" value={brl(rec.unallocated_brl)} note={`${fmt.num((rec.unallocated_brl / Math.max(rec.budget_brl, 1)) * 100, 0)}% do orçamento`} />
        <Fact
          label="Dados da análise"
          value={fresh}
          tone={dataTone}
          note={`Fechamento de ${fmt.day(rec.data_day)}; análise em ${fmtDateTime(rec.run_ts)}`}
        />
      </div>
    </Block>
  );
}

const SEGMENT_SHADE = ["bg-series-price", "bg-series-trend", "bg-series-average"] as const;

/** O orçamento dividido entre as moedas e o que fica sem investir, sempre somando 100%. */
function BudgetBar({ signals, rec }: { readonly signals: readonly DailySignal[]; readonly rec: Recommendation }) {
  const segments = budgetSegments(signals, rec);
  if (segments.length === 0) return null;
  return (
    <div className="mt-5">
      <div aria-hidden className="flex h-3 overflow-hidden rounded-sm bg-ground">
        {segments.map((s, i) =>
          s.key === "livre" ? null : (
            <span key={s.key} className={`${SEGMENT_SHADE[i % SEGMENT_SHADE.length] ?? ""} h-full border-r border-surface`} style={{ width: `${s.pct}%` }} />
          ),
        )}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
        {segments.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span aria-hidden className={`inline-block h-2.5 w-2.5 rounded-sm ${s.key === "livre" ? "bg-ground ring-1 ring-hairline" : SEGMENT_SHADE[i % SEGMENT_SHADE.length] ?? ""}`} />
            <span className="font-medium">{s.label}</span>
            <span className="num text-muted">{brl(s.amount)} ({fmt.num(s.pct, 0)}%)</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const COMPONENTS = [
  { key: "score_momentum", name: "Momento", term: "momento" },
  { key: "score_stability", name: "Persistência", term: "persistencia" },
  { key: "score_risk", name: "Risco (menor é melhor)", term: "volatilidade" },
  { key: "score_liquidity", name: "Liquidez", term: "liquidez" },
] as const;

function ScoreParts({ s }: { readonly s: DailySignal }) {
  return (
    <ul className="mt-2 space-y-1.5">
      {COMPONENTS.map((c) => {
        const v = s[c.key];
        return (
          <li key={c.key} className="grid grid-cols-[8.5rem_1fr_2.5rem] items-center gap-2 text-[13px]">
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

function PickCard({ s, index }: { readonly s: DailySignal; readonly index: number }) {
  const opp = OPPORTUNITY_LABEL[s.opportunity];
  const theoretical = s.theoretical_brl > s.allocation_brl + 0.5;
  return (
    <article aria-label={`Oportunidade ${index}: ${coinName(s.symbol)}`} className="flex flex-col rounded-md border border-hairline bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <span className="flex items-center gap-3">
          <span className="num text-[13px] text-muted">{index}.</span>
          <CoinLabel symbol={s.symbol} detailed size={30} />
        </span>
        <Badge tone={opp.tone}>{opp.text}</Badge>
      </div>
      <p className="mt-4 text-[13px] text-muted"><Term id="aporte">Aporte sugerido</Term></p>
      <p className="num text-[32px] font-medium leading-tight">{brl(s.allocation_brl)}</p>
      {theoretical && (
        <p className="mt-0.5 text-[13px] text-muted">
          <Term id="teorica">Alocação teórica</Term> {brl(Math.round(s.theoretical_brl * 100) / 100)}
        </p>
      )}
      {s.allocation_note !== null && <p className="mt-1 text-[13px] text-warning">{s.allocation_note}</p>}

      <p className="mt-4 flex items-baseline justify-between text-[13px]">
        <Term id="score">Score relativo</Term>
        <span className="num text-[15px] font-medium">{s.score === null ? "—" : `${fmt.num(s.score, 0)} de 100`}</span>
      </p>
      <ScoreParts s={s} />

      <h4 className="mt-4 text-[13px] font-medium text-muted">Por que</h4>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-[14px]">
        {s.reasons.map((r) => <li key={r}>{r}</li>)}
      </ul>
      <h4 className="mt-3 text-[13px] font-medium text-muted">Principais riscos</h4>
      {s.risks.length === 0 ? (
        <p className="mt-1 text-[14px]">Nenhum alerta além da oscilação normal de cripto.</p>
      ) : (
        <ul className="mt-1 list-disc space-y-1 pl-5 text-[14px]">
          {s.risks.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <dl className="mt-auto grid grid-cols-2 gap-3 border-t border-hairline pt-3 text-[13px]">
        <div>
          <dt className="text-muted">90 dias</dt>
          <dd className={`num font-medium ${TEXT_TONE[signTone(s.ret_90d_pct)]}`}>{fmt.pct(s.ret_90d_pct)}</dd>
        </div>
        <div>
          <dt className="text-muted"><Term id="volatilidade">Volatilidade</Term></dt>
          <dd className="num font-medium">{s.vol_90d_pct === null ? "—" : `${fmt.num(s.vol_90d_pct, 0)}% ao ano`}</dd>
        </div>
        <div>
          <dt className="text-muted">Preço</dt>
          <dd className="num font-medium">{fmt.price(s.close)}</dd>
        </div>
        <div>
          <dt className="text-muted"><Term id="custo">Custo estimado</Term></dt>
          <dd className="num font-medium">{s.est_cost_pct === null ? "—" : `${fmt.num(s.est_cost_pct, 2)}%`}</dd>
        </div>
      </dl>
    </article>
  );
}

/** Moedas descartadas com o motivo principal; a lista completa e os indicadores ficam na aba Seleção. */
export function DiscardedTable({ signals, limit }: { readonly signals: readonly DailySignal[]; readonly limit?: number }) {
  const rows = discarded(signals);
  const shown = limit === undefined ? rows : rows.slice(0, limit);
  return (
    <Table
      caption="Moedas não selecionadas e o que impede a compra"
      columns={[{ label: "Moeda" }, { label: "Classificação" }, { label: "Score", numeric: true, narrow: "hide" }, { label: "O que impede a compra" }]}
    >
      {shown.map((s) => (
        <tr key={s.symbol} className="border-b border-hairline align-top">
          <td className={cell}><CoinLabel symbol={s.symbol} /></td>
          <td className={cell}><Badge tone={OPPORTUNITY_LABEL[s.opportunity].tone}>{OPPORTUNITY_LABEL[s.opportunity].text}</Badge></td>
          <td className={`${numCell} ${hideNarrow}`}>{s.score === null ? "—" : fmt.num(s.score, 0)}</td>
          <td className={`${cell} whitespace-normal text-[14px]`}>
            {mainBlocker(s)}
            {s.blockers.length > 1 && <span className="text-muted"> (+{s.blockers.length - 1})</span>}
          </td>
        </tr>
      ))}
    </Table>
  );
}

/** Bloco principal da visão geral: a recomendação do dia. */
export function RecommendationPanel({ signals, rec, onDetails }: {
  readonly signals: readonly DailySignal[];
  readonly rec: Recommendation;
  readonly onDetails: () => void;
}) {
  const chosen = picks(signals);
  const none = rec.total_brl <= 0;
  return (
    <section aria-labelledby="recomendacao" className="space-y-6">
      <Block>
        <h2 id="recomendacao" className="flex items-center gap-2 text-lg font-semibold">
          <Wallet size={22} aria-hidden /> Recomendação de aporte
        </h2>
        <p className="mt-3 text-[22px] font-semibold leading-snug tracking-[-0.01em]">
          {none
            ? NO_OPPORTUNITY
            : `Considerar um aporte de ${brl(rec.total_brl)} de ${brl(rec.budget_brl)}, ou aguardar.`}
        </p>
        <p className="mt-1 text-muted">
          {none
            ? `Aporte sugerido: R$ 0 de ${brl(rec.budget_brl)}. O orçamento permanece sem alocação.`
            : `${brl(rec.unallocated_brl)} ficam sem investir. Moeda que oscila mais recebe menos; a soma nunca passa do orçamento.`}
        </p>
        <BudgetBar signals={signals} rec={rec} />
        {(rec.notes.length > 0 || rec.data_notes.length > 0) && (
          <ul className="mt-4 space-y-1 text-[14px]">
            {rec.data_notes.map((n) => <li key={n} className="text-warning">Limitação dos dados: {n}.</li>)}
            {rec.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}
        <p className="mt-4 max-w-[80ch] border-t border-hairline pt-3 text-[13px] text-muted">
          <strong className="font-medium text-ink">Validação histórica:</strong> {rec.evidence} Os valores são estimativas de
          dimensionamento do modelo quantitativo, não previsão de preço nem garantia de valorização. A{" "}
          <Term id="classificacao">classificação</Term> compara as moedas entre si e com filtros de risco; não é probabilidade de lucro.
        </p>
      </Block>

      {chosen.length > 0 && (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {chosen.map((s, i) => <PickCard key={s.symbol} s={s} index={i + 1} />)}
        </div>
      )}

      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="font-medium">Moedas descartadas nesta análise</h3>
          <button type="button" onClick={onDetails} className="flex items-center gap-1.5 text-[14px] font-medium text-signal hover:underline">
            <ListMagnifyingGlass size={18} aria-hidden /> Ver indicadores e backtest da seleção
          </button>
        </div>
        <p className="mt-1 text-[13px] text-muted">
          {rec.n_analyzed} moedas analisadas, {rec.n_candidates} com sinais favoráveis, {rec.n_funded} com aporte.
          {rec.excluded.length > 0 && ` Fora da análise: ${rec.excluded.join("; ")}.`}
        </p>
        <div className="mt-3"><DiscardedTable signals={signals} limit={8} /></div>
      </div>
    </section>
  );
}

const PERIOD_TEXT: Readonly<Record<LabPeriod, string>> = {
  TESTE: "Teste (2023 em diante)",
  VALIDACAO: "Validação (2021 e 2022)",
  TREINO: "Treino (2018 a 2020)",
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
    <div className="space-y-12">
      <section aria-labelledby="ranking">
        <h2 id="ranking" className="text-lg font-semibold">Ranking de todas as moedas analisadas</h2>
        <p className="mt-1 max-w-[72ch] text-muted">
          Componentes em percentil (0 a 100) contra as outras moedas do dia. O score soma os quatro com pesos fixos,
          definidos antes do teste (src/config.py). Análise de {fmtDateTime(rec.run_ts)}.
        </p>
        <div className="mt-4">
          <Table
            caption="Ranking da seleção com componentes do score, indicadores e aporte"
            columns={[
              { label: "Moeda" }, { label: "Classificação" }, { label: "Score", numeric: true },
              { label: "Momento", numeric: true, narrow: "hide" }, { label: "Persist.", numeric: true, narrow: "hide" },
              { label: "Risco", numeric: true, narrow: "hide" }, { label: "Liquidez", numeric: true, narrow: "hide" },
              { label: "30 dias", numeric: true, narrow: "hide" }, { label: "90 dias", numeric: true, narrow: "hide" },
              { label: "Vs. média 200", numeric: true, narrow: "hide" }, { label: "Volat.", numeric: true, narrow: "hide" },
              { label: "Condições", numeric: true, narrow: "hide" }, { label: "Aporte", numeric: true },
            ]}
          >
            {rows.map((s) => (
              <tr key={s.symbol} className="border-b border-hairline">
                <td className={cell}><CoinLabel symbol={s.symbol} /></td>
                <td className={cell}>
                  <span className="flex flex-col gap-1">
                    <Badge tone={OPPORTUNITY_LABEL[s.opportunity].tone}>{OPPORTUNITY_LABEL[s.opportunity].text}</Badge>
                    <span className="max-w-[28ch] whitespace-normal text-[12px] text-muted">
                      {s.selected ? label(s.reasons[0] ?? "") : mainBlocker(s)}
                    </span>
                  </span>
                </td>
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
              </tr>
            ))}
          </Table>
        </div>
      </section>

      <section aria-labelledby="bt-selecao">
        <h2 id="bt-selecao" className="text-lg font-semibold">A seleção funciona no passado?</h2>
        <p className="mt-1 max-w-[72ch] text-muted">
          A mesma seleção e o mesmo aporte do painel, refeitos a cada 7 dias com o orçamento de {brl(rec.budget_brl)}, contra
          referências simples, com a mesma execução para todas (sinal no fechamento, ordem na abertura do dia seguinte).
          Custos incluídos: taxa de 0,1% por lado, spread e slippage estimados. O teste não entrou em nenhuma escolha de
          peso ou limiar, mas já foi consultado no desenvolvimento: é um resultado exploratório.
        </p>
        <p className="mt-3 max-w-[72ch]">{rec.evidence}</p>
        {perf.length === 0 ? (
          <Block className="mt-4"><p className="text-muted">O backtest da seleção ainda não foi publicado. Rode o pipeline.</p></Block>
        ) : (
          <>
            <div className="mt-4"><Choice label="Período" value={period} options={PERIOD_TEXT} onChange={setPeriod} /></div>
            <div className="mt-4">
              <Table
                caption={`Backtest da seleção contra as referências, período ${PERIOD_TEXT[period]}, ordenado pelo Sharpe`}
                columns={[
                  { label: "Estratégia" }, { label: "Retorno total", numeric: true }, { label: "Por ano", numeric: true, narrow: "hide" },
                  { label: "Pior queda", numeric: true }, { label: "Sharpe", numeric: true }, { label: "Comprado", numeric: true, narrow: "hide" },
                  { label: "Giro por ano", numeric: true, narrow: "hide" }, { label: "Custos", numeric: true, narrow: "hide" },
                ]}
              >
                {shownPerf.map((r) => (
                  <tr key={r.strategy} className="border-b border-hairline">
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
            </div>
          </>
        )}
        <p className="mt-3 max-w-[72ch] text-[13px] text-muted">
          Limites: só entram moedas que existem hoje (as que quebraram não aparecem, o que favorece comprar altcoins); spread e
          slippage são estimados, não medidos; execução na abertura do dia seguinte (aproximação, não garantia); moeda que
          para de negociar com posição aberta conta como perda total; sem impostos. O estudo completo (referência aleatória,
          ano a ano, regimes de volatilidade e sensibilidade dos pesos) é gerado por research/selection_study.py.
        </p>
      </section>

      <section aria-labelledby="metodo">
        <h2 id="metodo" className="flex items-center gap-2 text-lg font-semibold"><Info size={22} aria-hidden /> Como a seleção decide</h2>
        <div className="mt-4 grid gap-6 md:grid-cols-3">
          <Block>
            <h3 className="font-medium">1. Filtros obrigatórios</h3>
            <p className="mt-2 text-[14px] text-muted">
              Sem dado recente ou com histórico curto, com <Term id="liquidez">liquidez</Term> baixa, volatilidade ou queda excessiva,
              ou abaixo da média de 200 dias: evitar entrada. Com o Bitcoin abaixo da média dele (mercado defensivo), nenhuma compra
              nova, por mais alto que seja o score.
            </p>
          </Block>
          <Block>
            <h3 className="font-medium">2. Score e classificação</h3>
            <p className="mt-2 text-[14px] text-muted">
              <Term id="momento">Momento</Term>, <Term id="persistencia">persistência</Term>, risco e liquidez viram percentis e somam
              o <Term id="score">score</Term>. Precisa também de várias condições favoráveis ao mesmo tempo e de preço não esticado.
              Nenhum sinal isolado (RSI baixo, alta recente, volume) autoriza compra.
            </p>
          </Block>
          <Block>
            <h3 className="font-medium">3. Quanto aportar</h3>
            <p className="mt-2 text-[14px] text-muted">
              Fração-alvo = risco-alvo ÷ volatilidade da moeda, com limite por moeda, metade para oportunidade moderada e corte pelo
              orçamento. Valores arredondados para baixo; abaixo da ordem mínima ou com custo alto, zero.
            </p>
          </Block>
        </div>
      </section>
    </div>
  );
}
