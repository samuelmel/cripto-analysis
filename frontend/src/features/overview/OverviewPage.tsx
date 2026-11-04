import { ArrowUpRight, CircleAlert, Database, ShieldQuestion, Target, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Async } from "../../components/data-display/Async";
import { PerformanceChart } from "../../components/charts/marketCharts";
import { PageHeader } from "../../components/layout/PageHeader";
import { Badge, EmptyState, InlineNote, Panel, SectionHeader, Stat } from "../../components/ui/primitives";
import { Hint } from "../../components/ui/tooltip";
import {
  OPPORTUNITY_LABEL,
  REGIME_LABEL,
  STAGE_LABEL,
  brl,
  dateShort,
  dateTime,
  decisionLabel,
  entryLabel,
  number,
  opportunityTone,
  pct,
  price,
  regimeTone,
  stageTone,
  toneForNumber,
} from "../../lib/format";
import type { Forecast, Overview, Signal } from "../../schemas/api";
import { useOverview } from "../../services/queries";

function decisionTone(decision: string): "positive" | "neutral" | "warning" {
  if (decision === "NAO_INVESTIR") return "warning";
  return "positive";
}

function AllocationBar({ signals, budget }: { signals: readonly Signal[]; budget: number }): ReactNode {
  const selected = signals.filter((signal) => signal.selected && signal.allocation_brl > 0);
  const allocated = selected.reduce((total, signal) => total + signal.allocation_brl, 0);
  const free = Math.max(0, budget - allocated);
  const colors = ["#0d6b63", "#4f7188", "#b05e34", "#7161a8"];
  if (budget <= 0) return null;
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-sunken">
        {selected.map((signal, index) => (
          <div
            key={signal.symbol}
            className="h-full"
            style={{ width: `${(signal.allocation_brl / budget) * 100}%`, backgroundColor: colors[index % colors.length] }}
            title={`${signal.symbol}: ${brl(signal.allocation_brl)}`}
          />
        ))}
        <div className="h-full" style={{ width: `${(free / budget) * 100}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
        {selected.map((signal, index) => (
          <span key={signal.symbol} className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ backgroundColor: colors[index % colors.length] }} />
            {signal.symbol.replace("/USDT", "")} · {brl(signal.allocation_brl, 0)}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5 text-faint">
          <span className="size-2 rounded-full bg-sunken" />
          não alocado · {brl(free, 0)}
        </span>
      </div>
    </div>
  );
}

function SelectedRow({ signal }: { signal: Signal }): ReactNode {
  return (
    <tr className="group border-t border-hairline align-top">
      <td className="py-3 pr-3">
        <Link to={`/mercado/${signal.symbol.replace("/USDT", "")}`} className="font-medium text-ink group-hover:text-signal">
          {signal.symbol}
        </Link>
        <div className="mt-1 flex flex-wrap gap-1">
          <Badge tone={opportunityTone(signal.opportunity)}>{OPPORTUNITY_LABEL[signal.opportunity]}</Badge>
          <Badge tone={stageTone(signal.stage)}>{STAGE_LABEL[signal.stage]}</Badge>
        </div>
      </td>
      <td className="num py-3 pr-3 text-right text-[13px]">{number(signal.score, 1)}</td>
      <td className="num py-3 pr-3 text-right text-[13px] font-medium">{brl(signal.allocation_brl, 0)}</td>
      <td className="py-3 pr-3">
        <div className="text-[12px] text-ink">{signal.reasons[0] ?? "Sem tese registrada."}</div>
        {signal.risks[0] ? <div className="mt-1 text-[11px] text-warning">{signal.risks[0]}</div> : null}
      </td>
      <td className="py-3 text-right">
        <Badge tone={signal.entry_level === "PROMISSOR" ? "warning" : "neutral"}>{entryLabel(signal.entry_level)}</Badge>
      </td>
    </tr>
  );
}

function OverviewBody({ data }: { data: Overview }): ReactNode {
  const recommendation = data.recommendation;
  const selected = data.signals
    .filter((signal) => signal.selected)
    .toSorted((a, b) => (a.candidate_rank ?? 99) - (b.candidate_rank ?? 99));
  const forecasts = data.forecast.filter((forecast) => forecast.role === "MODELO");
  const forecastSymbols = [...new Set(forecasts.map((forecast) => forecast.symbol))];
  const testRows = data.performance.filter((row) => row.period === "TESTE");
  const trend = testRows.find((row) => row.strategy === "TENDENCIA");
  const hold = testRows.find((row) => row.strategy === "COMPRAR_E_SEGURAR");
  const selectionTest = data.selection_performance
    .filter((row) => row.period === "TESTE")
    .toSorted((a, b) => (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity));
  const fngSignal = data.signals.find((signal) => signal.fng_value !== null);
  const warnings = data.system.status !== "ok";
  const selectedNote = selected.some((signal) => signal.entry_level === "PROMISSOR")
    ? "As moedas marcadas como “em observação” usam o score atual, o único sinal promissor do estudo de entradas. Nenhuma tem COMPRAR validado."
    : "Nenhuma moeda tem sinal COMPRAR validado. A seleção abaixo é a recomendação de aporte do painel, não uma promessa de retorno.";

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Visão geral"
        title="O que o sistema faria hoje."
        description="Uma leitura direta da recomendação publicada pelo pipeline: quanto alocar, por quê, o que a pesquisa sustenta e onde os dados ainda falham."
        meta={
          <>
            <span>Execução {dateTime(recommendation.run_ts)}</span>
            <span>Dados de {dateShort(recommendation.data_day)}</span>
            <span className="inline-flex items-center gap-1.5">
              <span className={`size-1.5 rounded-full ${warnings ? "bg-warning" : "bg-good"}`} />
              {warnings ? "Atenção nos dados" : "Artefatos coerentes"}
            </span>
          </>
        }
        actions={
          <>
            <Link
              to="/metodologia"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-hairline-strong bg-raised px-3 text-[13px] font-medium text-ink hover:bg-sunken"
            >
              <ShieldQuestion size={15} />
              Como ler
            </Link>
            <Link
              to="/mercado"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-signal bg-signal px-3 text-[13px] font-medium text-white hover:bg-signal-deep"
            >
              Ver mercado
              <ArrowUpRight size={14} />
            </Link>
          </>
        }
      />

      <section className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
        <div className="relative overflow-hidden border border-ink bg-ink p-5 text-white sm:p-7">
          <div className="pointer-events-none absolute inset-0 opacity-[0.075]">
            <TrendingUp className="absolute -right-7 -top-8 size-52" strokeWidth={0.6} />
          </div>
          <div className="relative">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-white/55">Decisão da análise</span>
              <Badge tone={decisionTone(recommendation.decision)} className="border-white/20 bg-white/10 text-white">
                <span className="size-1.5 rounded-full bg-current" />
                {decisionLabel(recommendation.decision)}
              </Badge>
            </div>
            <div className="mt-4 flex flex-wrap items-end gap-x-5 gap-y-2">
              <div className="num text-[42px] font-medium leading-none tracking-tight sm:text-[56px]">
                {brl(recommendation.total_brl, 0)}
              </div>
              <div className="pb-1 text-[12px] text-white/60">de {brl(recommendation.budget_brl, 0)} simulados</div>
            </div>
            <p className="mt-4 max-w-2xl text-[13px] leading-relaxed text-white/70">
              {recommendation.n_selected} de {recommendation.n_analyzed} moedas receberam aporte. O restante fica em caixa
              porque nenhuma outra candidata passou nos filtros de risco e liquidez.
            </p>
            <div className="mt-6">
              <AllocationBar signals={data.signals} budget={recommendation.budget_brl} />
            </div>
            <div className="mt-6 grid gap-4 border-t border-white/15 pt-4 sm:grid-cols-3">
              <div>
                <div className="text-[10px] uppercase tracking-[0.14em] text-white/45">Regime</div>
                <div className="mt-1 text-[14px]">{REGIME_LABEL[recommendation.regime]}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.14em] text-white/45">Candidatas</div>
                <div className="num mt-1 text-[14px]">{recommendation.n_candidates}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.14em] text-white/45">Não alocado</div>
                <div className="num mt-1 text-[14px]">{brl(recommendation.unallocated_brl, 0)}</div>
              </div>
            </div>
          </div>
        </div>

        <Panel className="grid grid-cols-2 gap-x-5 gap-y-6 p-5 sm:p-6">
          <Stat
            label="BTC / SMA 200"
            value={recommendation.regime_close ? `+${number(((recommendation.regime_close / (recommendation.regime_sma_200 ?? 1) - 1) * 100), 1)}%` : "—"}
            note={recommendation.regime_close ? price(recommendation.regime_close) : "sem leitura"}
            tone={regimeTone(recommendation.regime)}
          />
          <Stat
            label="Fear & Greed"
            value={fngSignal?.fng_value ?? "—"}
            note={fngSignal?.fng_classification ?? "sem leitura"}
            tone="neutral"
          />
          <Stat
            label="Amplitude"
            value={`${data.signals.filter((signal) => signal.uptrend).length} / ${data.signals.filter((signal) => !signal.uptrend).length}`}
            note="acima / abaixo da SMA 200"
          />
          <Stat
            label="Status dos dados"
            value={data.system.status === "ok" ? "OK" : data.system.status === "partial" ? "Parcial" : "Indisponível"}
            note={data.system.note}
            tone={data.system.status === "ok" ? "positive" : "warning"}
            mono={false}
          />
          <div className="col-span-2 border-t border-hairline pt-4">
            <InlineNote tone={warnings ? "warning" : "neutral"}>{data.system.note}</InlineNote>
          </div>
        </Panel>
      </section>

      <section>
        <SectionHeader
          eyebrow="Aporte sugerido"
          title="Carteira da análise"
          description={selectedNote}
          actions={<Badge tone="warning">{entryLabel("PROMISSOR")} não é COMPRAR</Badge>}
        />
        {selected.length === 0 ? (
          <div className="mt-5">
            <EmptyState
              title="Nenhuma moeda selecionada"
              description="O pipeline não encontrou candidatas que passassem em todos os filtros nesta execução."
            />
          </div>
        ) : (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[680px] border-collapse text-left">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.14em] text-faint">
                  <th className="pb-2 pr-3 font-medium">Ativo</th>
                  <th className="pb-2 pr-3 text-right font-medium">Score</th>
                  <th className="pb-2 pr-3 text-right font-medium">Aporte</th>
                  <th className="pb-2 pr-3 font-medium">Leitura</th>
                  <th className="pb-2 text-right font-medium">Entrada</th>
                </tr>
              </thead>
              <tbody>
                {selected.map((signal) => (
                  <SelectedRow key={signal.symbol} signal={signal} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="grid gap-8 xl:grid-cols-[1.2fr_1fr]">
        <div className="min-w-0">
          <SectionHeader
            eyebrow="Desempenho"
            title="A regra reduziu o tombo?"
            description="Retorno acumulado da regra SMA 200 contra comprar e segurar, nos mesmos períodos publicados."
          />
          <div className="mt-4 border border-hairline bg-surface p-3">
            <PerformanceChart rows={data.performance.filter((row) => row.universe === "PRINCIPAIS")} />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-[12px] text-muted sm:grid-cols-4">
            <div>
              <div className="text-faint">Trend · teste</div>
              <div className={`num mt-0.5 ${toneForNumber(trend?.total_return_pct)}`}>{pct(trend?.total_return_pct)}</div>
            </div>
            <div>
              <div className="text-faint">Segurar · teste</div>
              <div className={`num mt-0.5 ${toneForNumber(hold?.total_return_pct)}`}>{pct(hold?.total_return_pct)}</div>
            </div>
            <div>
              <div className="text-faint">Queda trend</div>
              <div className="num mt-0.5 text-ink">{pct(trend?.max_drawdown_pct)}</div>
            </div>
            <div>
              <div className="text-faint">Queda segurar</div>
              <div className="num mt-0.5 text-ink">{pct(hold?.max_drawdown_pct)}</div>
            </div>
          </div>
        </div>

        <div className="min-w-0">
          <SectionHeader
            eyebrow="Seleção"
            title="Estratégias no teste"
            description="Retorno anualizado e Sharpe no período de teste. A seleção não venceu comprar e segurar com folga."
            actions={<Hint text="Retorno anualizado e Sharpe publicados em selection_backtest.parquet. Não são recalculados pela API." />}
          />
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[480px] border-collapse text-left text-[12px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
                  <th className="border-b border-hairline pb-2 pr-3 font-medium">Estratégia</th>
                  <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Ano</th>
                  <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Sharpe</th>
                  <th className="border-b border-hairline pb-2 text-right font-medium">Queda</th>
                </tr>
              </thead>
              <tbody>
                {selectionTest.map((row) => (
                  <tr key={row.strategy} className="border-b border-hairline/70">
                    <td className="py-2 pr-3 text-ink">{row.strategy.replaceAll("_", " ")}</td>
                    <td className={`num py-2 pr-3 text-right ${toneForNumber(row.annual_return_pct)}`}>{pct(row.annual_return_pct)}</td>
                    <td className="num py-2 pr-3 text-right">{number(row.sharpe, 2)}</td>
                    <td className="num py-2 text-right text-muted">{pct(row.max_drawdown_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <SectionHeader
          eyebrow="Incerteza"
          title="Faixas prováveis, não previsão"
          description="P10–P90 do retorno para BTC e ETH. Nenhum modelo superou o passeio aleatório; a faixa mede incerteza."
          actions={<Badge tone="critical">sem vantagem demonstrada</Badge>}
        />
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {forecastSymbols.flatMap((symbol) =>
            forecasts
              .filter((forecast) => forecast.symbol === symbol)
              .map((forecast) => (
                <ForecastCell key={`${forecast.symbol}-${forecast.horizon_days}`} forecast={forecast} />
              )),
          )}
        </div>
      </section>

      <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        <StatusTile
          icon={<Target size={17} />}
          title="Sem COMPRAR validado"
          body="Nenhuma moeda passou no critério completo de validação. O painel sugere aportes, não um sinal de compra."
          to="/pesquisa"
          label="Ver evidência"
        />
        <StatusTile
          icon={<Database size={17} />}
          title="Base point-in-time"
          body="Preços usam apenas candles disponíveis na data. O universo histórico não é reconstruído pela API."
          to="/mercado"
          label="Explorar ativos"
        />
        <StatusTile
          icon={<CircleAlert size={17} />}
          title="Carteiras indisponíveis"
          body="Os arquivos de carteiras simuladas ainda não foram publicados. Nenhum valor é preenchido artificialmente."
          to="/carteiras"
          label="Ver estado"
        />
        <StatusTile
          icon={<ShieldQuestion size={17} />}
          title="Pesquisa aberta"
          body="Estudos rejeitados e inconclusivos aparecem com o mesmo peso dos promissores."
          to="/pesquisa"
          label="Ler estudos"
        />
      </section>
    </div>
  );
}

function ForecastCell({ forecast }: { forecast: Forecast }): ReactNode {
  const last = forecast.last_close;
  const spread = Math.max(forecast.p90_price - forecast.p10_price, 1);
  const clamp = (value: number): number => Math.min(100, Math.max(0, ((value - forecast.p10_price) / spread) * 100));
  return (
    <div className="border border-hairline bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[11px] uppercase tracking-[0.12em] text-faint">{forecast.symbol}</div>
          <div className="mt-1 text-[15px] font-semibold">{forecast.horizon_days} dias</div>
        </div>
        <Badge tone="neutral">{forecast.method.replaceAll("_", " ").toLowerCase()}</Badge>
      </div>
      <div className="num mt-3 text-[22px] font-medium">{price(forecast.p50_price)}</div>
      <div className="mt-3 h-1.5 rounded-full bg-sunken">
        <div
          className="h-1.5 rounded-full bg-signal/25"
          style={{ marginLeft: `${clamp(forecast.p10_price)}%`, width: `${Math.max(2, clamp(forecast.p90_price) - clamp(forecast.p10_price))}%` }}
        />
      </div>
      <div className="num mt-2 flex justify-between text-[11px] text-muted">
        <span>{price(forecast.p10_price)}</span>
        <span>{price(forecast.p90_price)}</span>
      </div>
      <div className="mt-2 text-[11px] text-faint">
        Hoje {price(last)} · mediana {pct(((forecast.p50_price - last) / last) * 100)}
      </div>
    </div>
  );
}

function StatusTile({
  icon,
  title,
  body,
  to,
  label,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  to: string;
  label: string;
}): ReactNode {
  return (
    <Link to={to} className="group border-t-2 border-hairline-strong pt-3 hover:border-signal">
      <div className="text-faint group-hover:text-signal">{icon}</div>
      <h3 className="mt-2 text-[14px] font-semibold text-ink">{title}</h3>
      <p className="mt-1 text-[12px] leading-relaxed text-muted">{body}</p>
      <span className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-signal">
        {label} <ArrowUpRight size={12} />
      </span>
    </Link>
  );
}

export function OverviewPage(): ReactNode {
  const query = useOverview();
  return <Async<Overview> query={query}>{(data) => <OverviewBody data={data} />}</Async>;
}
