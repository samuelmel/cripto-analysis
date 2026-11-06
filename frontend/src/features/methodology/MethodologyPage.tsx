import { Database, GitBranch, ShieldCheck, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Async } from "../../components/data-display/Async";
import { PageHeader } from "../../components/layout/PageHeader";
import { Badge, InlineNote, Panel, SectionHeader } from "../../components/ui/primitives";
import { dateShort, dateTime } from "../../lib/format";
import type { Overview } from "../../schemas/api";
import { useOverview } from "../../services/queries";

const RULES = [
  {
    title: "Dados point-in-time",
    body: "Cada linha usa somente candles disponíveis na data de referência. O universo histórico não é reconstruído com a lista de moedas de hoje.",
  },
  {
    title: "Recomendação sem ordens",
    body: "A API lê daily_signals.parquet e recommendation.parquet. Não envia ordens, não altera o motor next-open-v1 e não recalcula sinais.",
  },
  {
    title: "Aporte é orçamento",
    body: "A seleção distribui um orçamento fixo de R$ 100 entre candidatas. Aporte não é preço-alvo, promessa de retorno nem tamanho de posição real.",
  },
  {
    title: "Pesquisa aberta",
    body: "Estudos rejeitados, inconclusivos e compatíveis com sorte aparecem no painel. Nenhum resultado é promovido por conveniência editorial.",
  },
] as const;

const LIMITS = [
  "Não há cotação USDT/BRL publicada; valores em reais usam apenas o câmbio congelado do artefato de recomendação.",
  "As carteiras simuladas não estão disponíveis; patrimônio, posições e curvas não são estimados.",
  "Previsões são faixas P10–P90, não um caminho provável. Nenhum modelo superou o passeio aleatório de forma consistente.",
  "Score atual não é sinal validado. PROMISSOR significa observação, não COMPRAR.",
  "A data de referência pode estar defasada em relação ao dia de acesso; o cabeçalho mostra a data real dos dados.",
] as const;

function MethodologyBody({ data }: { data: Overview }): ReactNode {
  const system = data.system;
  return (
    <div className="space-y-9">
      <PageHeader
        eyebrow="Metodologia e dados"
        title="O que este painel pode afirmar."
        description="As regras de leitura, a origem de cada número e os limites que impedem transformar pesquisa em recomendação individual."
        meta={
          <>
            <span>API v{system.api_version}</span>
            <span>branch {system.state_branch}</span>
            <span>status {system.status}</span>
            <span>gerado em {dateTime(system.generated_at)}</span>
          </>
        }
        actions={<Badge tone={system.status === "ok" ? "positive" : "warning"}>{system.status.toUpperCase()}</Badge>}
      />

      <section className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {RULES.map((rule, index) => (
          <div key={rule.title} className="border-t-2 border-hairline-strong pt-3">
            <div className="num text-[11px] text-signal">{String(index + 1).padStart(2, "0")}</div>
            <h2 className="mt-1 text-[14px] font-semibold text-ink">{rule.title}</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">{rule.body}</p>
          </div>
        ))}
      </section>

      <section className="grid gap-8 xl:grid-cols-[1fr_1.25fr]">
        <div className="min-w-0">
          <SectionHeader eyebrow="Limites" title="O que não é feito" />
          <ul className="mt-4 space-y-3">
            {LIMITS.map((limit, index) => (
              <li key={`${index}-${limit}`} className="flex gap-2 border-b border-hairline/70 pb-3 text-[12px] leading-relaxed text-muted">
                <TriangleAlert size={14} className="mt-0.5 shrink-0 text-warning" />
                {limit}
              </li>
            ))}
          </ul>
          <div className="mt-5">
            <InlineNote tone="warning">{system.note}</InlineNote>
          </div>
        </div>

        <div className="min-w-0">
          <SectionHeader
            eyebrow="Estado"
            title="Artefatos publicados"
            description="Cada arquivo tem status, linhas e última data. Um artefato ausente aparece como ausente."
            actions={<Database size={17} className="text-faint" />}
          />
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[500px] border-collapse text-left text-[12px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
                  <th className="border-b border-hairline pb-2 pr-3 font-medium">Artefato</th>
                  <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Linhas</th>
                  <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Última data</th>
                  <th className="border-b border-hairline pb-2 text-right font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {system.artifacts.map((artifact) => (
                  <tr key={artifact.name} className="border-b border-hairline/70">
                    <td className="py-2.5 pr-3">
                      <div className="text-ink">{artifact.name}</div>
                      {artifact.note ? <div className="mt-0.5 text-[10px] text-faint">{artifact.note}</div> : null}
                    </td>
                    <td className="num py-2.5 pr-3 text-right text-muted">{artifact.rows ?? "—"}</td>
                    <td className="num py-2.5 pr-3 text-right text-muted">
                      {artifact.last_data_ts ? dateShort(artifact.last_data_ts) : "—"}
                    </td>
                    <td className="py-2.5 text-right">
                      <Badge tone={artifact.status === "ok" ? "positive" : artifact.status === "stale" ? "warning" : "critical"}>
                        {artifact.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <SectionHeader
          eyebrow="Procedência"
          title="Fontes e cobertura"
          description="O status reflete a leitura do arquivo publicado, não uma chamada ao provedor em tempo real."
          actions={<GitBranch size={17} className="text-faint" />}
        />
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {system.source_health.map((source, index) => (
            <div key={`${index}-${source.source}`} className="border border-hairline bg-surface p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="text-[12px] font-medium text-ink">{source.source}</div>
                <Badge tone={source.status === "ok" ? "positive" : "critical"}>{source.status}</Badge>
              </div>
              <div className="mt-1 text-[11px] text-muted">{source.scope}</div>
              <div className="num mt-3 flex justify-between text-[10px] text-faint">
                <span>{source.rows} linhas</span>
                <span>{source.last_data_ts ? dateShort(source.last_data_ts) : "sem data"}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <Panel className="grid gap-5 p-5 sm:grid-cols-3 sm:p-6">
        <div className="flex gap-3">
          <ShieldCheck size={18} className="mt-0.5 shrink-0 text-signal" />
          <div>
            <div className="text-[13px] font-medium text-ink">Somente leitura</div>
            <div className="mt-1 text-[12px] text-muted">A API expõe GET e HEAD. Nenhuma rota altera artefatos.</div>
          </div>
        </div>
        <div className="flex gap-3">
          <Database size={18} className="mt-0.5 shrink-0 text-signal" />
          <div>
            <div className="text-[13px] font-medium text-ink">Parquet</div>
            <div className="mt-1 text-[12px] text-muted">Dados brutos, intermediários e saída usam Parquet com Snappy.</div>
          </div>
        </div>
        <div className="flex gap-3">
          <GitBranch size={18} className="mt-0.5 shrink-0 text-signal" />
          <div>
            <div className="text-[13px] font-medium text-ink">Estado isolado</div>
            <div className="mt-1 text-[12px] text-muted">O repositório de estado é lido, nunca escrito pelo painel.</div>
          </div>
        </div>
      </Panel>
    </div>
  );
}

export function MethodologyPage(): ReactNode {
  const query = useOverview();
  return <Async<Overview> query={query}>{(data) => <MethodologyBody data={data} />}</Async>;
}
