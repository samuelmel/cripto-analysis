import { ArrowUpRight, BookOpen, FlaskConical, SearchX } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Async } from "../../components/data-display/Async";
import { PageHeader } from "../../components/layout/PageHeader";
import { SegmentedTabs } from "../../components/ui/tabs";
import { Badge, EmptyState, InlineNote, Panel, SectionHeader, Stat } from "../../components/ui/primitives";
import { Hint } from "../../components/ui/tooltip";
import { dateTime, entryLabel, number, pct, toneForNumber } from "../../lib/format";
import type { EntryLevel, LabResult, ResearchData, ResearchStudy } from "../../schemas/api";
import { useResearch } from "../../services/queries";

type Filter = "todos" | ResearchStudy["status"];

const FILTERS: readonly { value: Filter; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "validado", label: "Validado" },
  { value: "promissor", label: "Promissor" },
  { value: "inconclusivo", label: "Inconclusivo" },
  { value: "compativel_com_sorte", label: "Sorte" },
  { value: "rejeitado", label: "Rejeitado" },
  { value: "experimental", label: "Experimental" },
];

function studyTone(status: ResearchStudy["status"]): "positive" | "neutral" | "warning" | "critical" {
  if (status === "validado") return "positive";
  if (status === "promissor" || status === "experimental") return "warning";
  if (status === "rejeitado") return "critical";
  return "neutral";
}

function entryTone(level: EntryLevel["level"]): "positive" | "warning" | "neutral" {
  if (level === "VALIDADO") return "positive";
  if (level === "PROMISSOR") return "warning";
  return "neutral";
}

function StudyRow({ study }: { study: ResearchStudy }): ReactNode {
  return (
    <Link
      to={`/pesquisa/${study.id}`}
      className="group grid gap-3 border-t border-hairline py-5 transition-colors hover:bg-sunken/50 sm:grid-cols-[1fr_auto] sm:px-2"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={studyTone(study.status)}>{study.status_label}</Badge>
          <span className="text-[10px] uppercase tracking-[0.12em] text-faint">{study.category}</span>
        </div>
        <h3 className="mt-2 text-[16px] font-semibold text-ink group-hover:text-signal">{study.title}</h3>
        <p className="mt-1 max-w-4xl text-[12px] leading-relaxed text-muted">{study.summary}</p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-faint">
          <span>{study.periods}</span>
          <span>{study.sample}</span>
          <span>{study.docs.length} documentos</span>
        </div>
      </div>
      <div className="flex items-start gap-4 sm:flex-col sm:items-end">
        <div className="text-right">
          <div className="num text-[18px] font-medium text-ink">{study.metrics[0]?.value ?? "—"}</div>
          <div className="text-[10px] text-faint">{study.metrics[0]?.name ?? "sem métrica"}</div>
        </div>
        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-signal">
          abrir <ArrowUpRight size={12} />
        </span>
      </div>
    </Link>
  );
}

function Studies({ data, filter }: { data: ResearchData; filter: Filter }): ReactNode {
  const studies = filter === "todos" ? data.studies : data.studies.filter((study) => study.status === filter);
  if (studies.length === 0) {
    return <EmptyState icon={<SearchX size={22} />} title="Nenhum estudo neste filtro" description="Troque o filtro para ver outros resultados." />;
  }
  return (
    <div className="mt-4 border-b border-hairline">
      {studies.map((study) => (
        <StudyRow key={study.id} study={study} />
      ))}
    </div>
  );
}

function LabTable({ rows }: { rows: readonly LabResult[] }): ReactNode {
  const filtered = rows.filter((row) => row.universe === "PRINCIPAIS");
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-left text-[12px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
            <th className="border-b border-hairline pb-2 pr-3 font-medium">Estratégia</th>
            <th className="border-b border-hairline pb-2 pr-3 font-medium">Período</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Total</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Ano</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Queda</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Sharpe</th>
            <th className="border-b border-hairline pb-2 text-right font-medium">Investido</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((row) => (
            <tr key={`${row.strategy}-${row.period}`} className="border-b border-hairline/70">
              <td className="py-2.5 pr-3 text-ink">{row.strategy.replaceAll("_", " ")}</td>
              <td className="py-2.5 pr-3 text-muted">{row.period}</td>
              <td className={`num py-2.5 pr-3 text-right ${toneForNumber(row.total_return_pct)}`}>{pct(row.total_return_pct)}</td>
              <td className={`num py-2.5 pr-3 text-right ${toneForNumber(row.annual_return_pct)}`}>{pct(row.annual_return_pct)}</td>
              <td className="num py-2.5 pr-3 text-right text-muted">{pct(row.max_drawdown_pct)}</td>
              <td className="num py-2.5 pr-3 text-right">{number(row.sharpe, 2)}</td>
              <td className="num py-2.5 text-right text-muted">{pct(row.invested_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EntryTable({ rows }: { rows: readonly EntryLevel[] }): ReactNode {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-left text-[12px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
            <th className="border-b border-hairline pb-2 pr-3 font-medium">Combo</th>
            <th className="border-b border-hairline pb-2 pr-3 font-medium">Candidata</th>
            <th className="border-b border-hairline pb-2 pr-3 font-medium">Nível</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Excesso 7d</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Excesso 30d</th>
            <th className="border-b border-hairline pb-2 font-medium">Razão</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${index}-${row.combo}-${row.candidate}`} className="border-b border-hairline/70">
              <td className="py-2.5 pr-3 text-ink">{row.combo.replaceAll("_", " ")}</td>
              <td className="py-2.5 pr-3">{row.candidate}</td>
              <td className="py-2.5 pr-3">
                <Badge tone={entryTone(row.level)}>{entryLabel(row.level)}</Badge>
              </td>
              <td className={`num py-2.5 pr-3 text-right ${toneForNumber(row.excess_7)}`}>{pct(row.excess_7)}</td>
              <td className={`num py-2.5 pr-3 text-right ${toneForNumber(row.excess_30)}`}>{pct(row.excess_30)}</td>
              <td className="max-w-[260px] py-2.5 text-[11px] leading-snug text-muted">{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResearchBody({ data }: { data: ResearchData }): ReactNode {
  const [filter, setFilter] = useState<Filter>("todos");
  const counts = FILTERS.map((option) => ({
    value: option.value,
    label: option.label,
    count: option.value === "todos" ? data.studies.length : data.studies.filter((study) => study.status === option.value).length,
  })).filter((option) => option.value === "todos" || option.count > 0);
  const validated = data.evidence.validated_symbols;

  return (
    <div className="space-y-9">
      <PageHeader
        eyebrow="Pesquisa quantitativa"
        title="O que sobreviveu ao teste."
        description="Dez estudos, seis estratégias e doze combinações de entrada. O painel mostra também o que falhou: um resultado rejeitado não é escondido."
        meta={
          <>
            <span>{data.studies.length} estudos</span>
            <span>{data.lab.length} resultados de laboratório</span>
            <span>congelado em {dateTime(data.generated_at)}</span>
          </>
        }
        actions={
          <Badge tone={data.evidence.validated > 0 ? "positive" : "critical"}>
            {data.evidence.validated} validadas
          </Badge>
        }
      />

      <section className="grid grid-cols-2 gap-x-5 gap-y-5 border-y border-hairline py-5 sm:grid-cols-3 xl:grid-cols-5">
        <Stat label="Evidências" value={data.evidence.total} note="moedas com histórico point-in-time" />
        <Stat label="Validadas" value={data.evidence.validated} note="passaram no holdout" tone="positive" />
        <Stat label="Não validadas" value={data.evidence.not_validated} note="testadas e falharam" tone="warning" />
        <Stat label="Sem evidência" value={data.evidence.no_evidence} note="amostra insuficiente" />
        <Stat label="Revogadas" value={data.evidence.revoked} note="perderam a evidência" tone="critical" />
        <div className="col-span-2 sm:col-span-3 xl:col-span-5">
          <InlineNote tone={validated.length > 0 ? "neutral" : "warning"}>
            {validated.length > 0
              ? `Símbolos validados: ${validated.join(", ")}.`
              : "Nenhuma moeda passou em validação completa. As recomendações de aporte usam o score atual e níveis PROMISSOR, não um sinal COMPRAR."}
          </InlineNote>
        </div>
      </section>

      <section>
        <SectionHeader
          eyebrow="Estudos"
          title="Perguntas e respostas"
          description="Cada estudo declara período, universo, amostra, achados e limitações. O status não é uma recomendação de compra."
          actions={<FlaskConical size={18} className="text-faint" />}
        />
        <div className="mt-4">
          <SegmentedTabs value={filter} onValueChange={(value) => setFilter(value as Filter)} options={counts} label="Filtrar estudos por status" />
        </div>
        <Studies data={data} filter={filter} />
      </section>

      <section>
        <SectionHeader
          eyebrow="Laboratório"
          title="Estratégias no mesmo banco de dados"
          description="Resultados publicados para o universo das principais moedas. Retorno não é lucro garantido: o período e o universo mudam a conclusão."
          actions={<Hint text="Fonte: frontend/public/strategy_lab.parquet. A API não recalcula os testes." />}
        />
        <div className="mt-4">
          <LabTable rows={data.lab} />
        </div>
      </section>

      <section>
        <SectionHeader
          eyebrow="Entradas"
          title="O que cada combinação mostrou"
          description="Níveis por combinação de sinal. PROMISSOR indica que o resultado merece observação, não que o retorno se repetirá."
          actions={<Badge tone="warning">1 promissor · 0 validado</Badge>}
        />
        <div className="mt-4">
          <EntryTable rows={data.entry_levels} />
        </div>
      </section>

      <Panel className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <BookOpen size={18} className="mt-0.5 shrink-0 text-signal" />
          <div>
            <div className="text-[13px] font-medium text-ink">Como os estudos são atualizados</div>
            <div className="mt-1 text-[12px] text-muted">
              A pesquisa roda fora do painel. A API apenas lê os artefatos publicados e o catálogo editorial do código.
            </div>
          </div>
        </div>
        <Link to="/metodologia" className="inline-flex shrink-0 items-center gap-1 text-[12px] font-medium text-signal">
          Metodologia <ArrowUpRight size={13} />
        </Link>
      </Panel>
    </div>
  );
}

export function ResearchPage(): ReactNode {
  const query = useResearch();
  return <Async<ResearchData> query={query}>{(data) => <ResearchBody data={data} />}</Async>;
}
