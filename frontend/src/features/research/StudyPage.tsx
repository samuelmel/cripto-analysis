import { ArrowLeft, FileText, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { Async } from "../../components/data-display/Async";
import { PageHeader } from "../../components/layout/PageHeader";
import { Badge, EmptyState, InlineNote, Panel, SectionHeader } from "../../components/ui/primitives";
import { dateTime, number } from "../../lib/format";
import type { ResearchData, ResearchStudy } from "../../schemas/api";
import { useResearch } from "../../services/queries";

function studyTone(status: ResearchStudy["status"]): "positive" | "neutral" | "warning" | "critical" {
  if (status === "validado") return "positive";
  if (status === "promissor" || status === "experimental") return "warning";
  if (status === "rejeitado") return "critical";
  return "neutral";
}

function StudyDetail({ study }: { study: ResearchStudy }): ReactNode {
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={study.category}
        title={study.title}
        description={study.summary}
        meta={
          <>
            <Badge tone={studyTone(study.status)}>{study.status_label}</Badge>
            <span>{study.periods}</span>
            <span>{study.universe}</span>
            <span>atualizado em {dateTime(study.updated_at)}</span>
          </>
        }
        actions={
          <Link
            to="/pesquisa"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-hairline-strong bg-raised px-3 text-[13px] font-medium text-ink hover:bg-sunken"
          >
            <ArrowLeft size={14} />
            Voltar
          </Link>
        }
      />

      <div className="grid gap-8 xl:grid-cols-[1.35fr_1fr]">
        <div className="space-y-8">
          <Panel className="p-5 sm:p-6">
            <SectionHeader eyebrow="Pergunta" title="O que foi testado" />
            <p className="mt-4 text-[14px] leading-relaxed text-ink">{study.question}</p>
            <div className="mt-5 grid grid-cols-2 gap-4 border-t border-hairline pt-4 text-[12px]">
              <div>
                <div className="text-[10px] uppercase tracking-[0.13em] text-faint">Amostra</div>
                <div className="mt-1 text-muted">{study.sample}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.13em] text-faint">Universo</div>
                <div className="mt-1 text-muted">{study.universe}</div>
              </div>
            </div>
          </Panel>

          <section>
            <SectionHeader eyebrow="Achados" title="O que os números mostram" />
            <div className="mt-4 space-y-0 border-b border-hairline">
              {study.findings.map((finding) => (
                <div key={finding.title} className="border-t border-hairline py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={finding.tone}>{finding.tone === "positive" ? "favorável" : finding.tone}</Badge>
                    <h3 className="text-[14px] font-semibold text-ink">{finding.title}</h3>
                  </div>
                  <p className="mt-2 text-[13px] leading-relaxed text-muted">{finding.detail}</p>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="space-y-8">
          <section>
            <SectionHeader eyebrow="Métricas" title="Números publicados" />
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[320px] border-collapse text-left text-[12px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
                    <th className="border-b border-hairline pb-2 pr-3 font-medium">Métrica</th>
                    <th className="border-b border-hairline pb-2 pr-3 font-medium">Período</th>
                    <th className="border-b border-hairline pb-2 text-right font-medium">Valor</th>
                  </tr>
                </thead>
                <tbody>
                  {study.metrics.map((metric) => (
                    <tr key={`${metric.name}-${metric.period}`} className="border-b border-hairline/70">
                      <td className="py-2.5 pr-3">
                        <div className="text-ink">{metric.name.replaceAll("_", " ")}</div>
                        {metric.note ? <div className="mt-0.5 text-[10px] text-faint">{metric.note}</div> : null}
                      </td>
                      <td className="py-2.5 pr-3 text-muted">{metric.period}</td>
                      <td className="num py-2.5 text-right">
                        {metric.value === null ? "—" : `${number(metric.value, metric.unit === "%" ? 2 : 3)}${metric.unit}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <Panel className="p-5">
            <div className="flex items-center gap-2">
              <ShieldAlert size={17} className="text-warning" />
              <h2 className="text-[14px] font-semibold text-ink">Limitações</h2>
            </div>
            <ul className="mt-3 space-y-2">
              {study.limitations.map((limitation) => (
                <li key={limitation} className="flex gap-2 text-[12px] leading-relaxed text-muted">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-warning" />
                  {limitation}
                </li>
              ))}
            </ul>
          </Panel>

          <section>
            <SectionHeader eyebrow="Rastro" title="Documentos" />
            {study.docs.length === 0 ? (
              <div className="mt-4">
                <InlineNote>Nenhum documento vinculado a este estudo.</InlineNote>
              </div>
            ) : (
              <ul className="mt-4 space-y-2">
                {study.docs.map((doc) => (
                  <li key={doc} className="flex items-start gap-2 border-b border-hairline/70 pb-2 text-[12px] text-muted">
                    <FileText size={14} className="mt-0.5 shrink-0 text-faint" />
                    <code className="break-all font-mono text-[11px]">{doc}</code>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function StudyBody({ data }: { data: ResearchData }): ReactNode {
  const { studyId } = useParams<{ studyId: string }>();
  const study = data.studies.find((item) => item.id === studyId);
  if (!study) {
    return (
      <EmptyState
        title="Estudo não encontrado"
        description="O identificador não existe no catálogo publicado."
        action={
          <Link to="/pesquisa" className="inline-flex items-center gap-1 text-[12px] font-medium text-signal">
            <ArrowLeft size={13} /> Voltar para pesquisa
          </Link>
        }
      />
    );
  }
  return <StudyDetail study={study} />;
}

export function StudyPage(): ReactNode {
  const query = useResearch();
  return <Async<ResearchData> query={query}>{(data) => <StudyBody data={data} />}</Async>;
}
