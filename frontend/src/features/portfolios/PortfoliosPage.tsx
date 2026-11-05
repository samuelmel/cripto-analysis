import { ArrowUpRight, CircleAlert, WalletCards } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Async } from "../../components/data-display/Async";
import { PageHeader } from "../../components/layout/PageHeader";
import { Badge, EmptyState, InlineNote, Panel, SectionHeader, Stat } from "../../components/ui/primitives";
import { brl, dateShort, number, pct, toneForNumber } from "../../lib/format";
import type { AiStatus, PortfolioDetail, PortfolioSummary, PortfoliosData } from "../../schemas/api";
import { usePortfolio, usePortfolios } from "../../services/queries";

function statusTone(status: PortfolioSummary["status"]): "positive" | "neutral" | "warning" {
  if (status === "available") return "positive";
  if (status === "reference") return "neutral";
  return "warning";
}

function statusLabel(status: PortfolioSummary["status"]): string {
  if (status === "available") return "disponível";
  if (status === "reference") return "referência";
  return "sem dados";
}

function PortfolioTile({
  portfolio,
  selected,
  onSelect,
}: {
  portfolio: PortfolioSummary;
  selected: boolean;
  onSelect: () => void;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group border p-4 text-left transition-colors ${
        selected ? "border-signal bg-signal-wash/60" : "border-hairline bg-surface hover:border-hairline-strong"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-faint">{portfolio.id}</div>
          <div className="mt-1 text-[15px] font-semibold text-ink">{portfolio.name}</div>
        </div>
        <Badge tone={statusTone(portfolio.status)}>{statusLabel(portfolio.status)}</Badge>
      </div>
      <div className="mt-4">
        {portfolio.total_brl !== null ? (
          <div className="num text-[20px] font-medium text-ink">{brl(portfolio.total_brl, 0)}</div>
        ) : (
          <div className="text-[13px] text-muted">Sem patrimônio publicado</div>
        )}
        <div className="mt-1 flex gap-3 text-[11px] text-muted">
          {portfolio.return_pct !== null ? <span className={toneForNumber(portfolio.return_pct)}>{pct(portfolio.return_pct)}</span> : null}
          {portfolio.n_coins !== null ? <span>{portfolio.n_coins} moedas</span> : null}
          {portfolio.as_of ? <span>{dateShort(portfolio.as_of)}</span> : null}
        </div>
      </div>
      <div className="mt-3 line-clamp-2 text-[11px] leading-relaxed text-faint">{portfolio.rule}</div>
      <span className="mt-3 inline-flex items-center gap-1 text-[11px] font-medium text-signal">
        {selected ? "em foco" : "abrir"} <ArrowUpRight size={12} />
      </span>
    </button>
  );
}

function Positions({ detail }: { detail: PortfolioDetail }): ReactNode {
  if (detail.positions.length === 0) {
    return (
      <EmptyState
        title="Sem posições abertas publicadas"
        description={detail.note || "A API não encontrou posições para esta carteira na data de referência."}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] border-collapse text-left text-[12px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
            <th className="border-b border-hairline pb-2 pr-3 font-medium">Ativo</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Lotes</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Valor</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Retorno</th>
            <th className="border-b border-hairline pb-2 text-right font-medium">1ª compra</th>
          </tr>
        </thead>
        <tbody>
          {detail.positions.map((position) => (
            <tr key={position.symbol} className="border-b border-hairline/70">
              <td className="py-2.5 pr-3 font-medium text-ink">{position.symbol}</td>
              <td className="num py-2.5 pr-3 text-right">{position.n_lots}</td>
              <td className="num py-2.5 pr-3 text-right">{brl(position.value_brl, 0)}</td>
              <td className={`num py-2.5 pr-3 text-right ${toneForNumber(position.return_pct)}`}>{pct(position.return_pct)}</td>
              <td className="num py-2.5 text-right text-muted">{dateShort(position.first_buy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DetailBody({ detail }: { detail: PortfolioDetail }): ReactNode {
  const portfolio = detail.portfolio;
  const available = portfolio.status === "available";
  const reference = portfolio.status === "reference";
  return (
    <div className="grid gap-8 xl:grid-cols-[1.3fr_1fr]">
      <div className="min-w-0">
        <SectionHeader
          eyebrow={portfolio.id}
          title={portfolio.name}
          description={portfolio.rule}
          actions={<Badge tone={statusTone(portfolio.status)}>{statusLabel(portfolio.status)}</Badge>}
        />
        {portfolio.status === "unavailable" ? (
          <div className="mt-5">
            <InlineNote tone="warning">{portfolio.note || "Arquivo de carteira ainda não publicado."}</InlineNote>
          </div>
        ) : null}
        <div className="mt-5 grid grid-cols-2 gap-x-5 gap-y-5 border-y border-hairline py-5 sm:grid-cols-4">
          <Stat label="Patrimônio" value={portfolio.total_brl !== null ? brl(portfolio.total_brl, 0) : "—"} note={portfolio.currency} />
          <Stat
            label="Retorno"
            value={pct(portfolio.return_pct)}
            tone={portfolio.return_pct !== null && portfolio.return_pct >= 0 ? "positive" : "critical"}
          />
          <Stat label="Caixa" value={portfolio.cash_brl !== null ? brl(portfolio.cash_brl, 0) : "—"} note="BRL" />
          <Stat label="Posições" value={portfolio.n_coins ?? "—"} note={portfolio.n_buys !== null ? `${portfolio.n_buys} compras` : "sem execução"} />
        </div>
        <div className="mt-6">
          <h3 className="text-[12px] font-medium uppercase tracking-[0.13em] text-faint">Posições</h3>
          <div className="mt-3">
            <Positions detail={detail} />
          </div>
        </div>
        <div className="mt-6">
          <InlineNote tone={available ? "neutral" : "warning"}>{detail.note || portfolio.note}</InlineNote>
        </div>
      </div>

      <div className="min-w-0">
        <SectionHeader
          eyebrow="Métricas"
          title={reference ? "Referência de estudo" : "Desempenho simulado"}
          description={reference ? "Métricas do laboratório de estratégias, não de uma carteira executada." : "Métricas publicadas para a carteira."}
        />
        {detail.metrics.length === 0 ? (
          <div className="mt-5">
            <EmptyState title="Sem métricas" description="Não há métricas publicadas para esta carteira." />
          </div>
        ) : (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[430px] border-collapse text-left text-[12px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
                  <th className="border-b border-hairline pb-2 pr-3 font-medium">Métrica</th>
                  <th className="border-b border-hairline pb-2 pr-3 font-medium">Período</th>
                  <th className="border-b border-hairline pb-2 text-right font-medium">Valor</th>
                </tr>
              </thead>
              <tbody>
                {detail.metrics.map((metric) => (
                  <tr key={`${metric.name}-${metric.period}`} className="border-b border-hairline/70">
                    <td className="py-2.5 pr-3 text-ink">{metric.name.replaceAll("_", " ")}</td>
                    <td className="py-2.5 pr-3 text-muted">{metric.period}</td>
                    <td className="num py-2.5 text-right">
                      {metric.value === null ? "—" : `${number(metric.value, metric.unit === "%" ? 2 : 3)}${metric.unit}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-5 border border-hairline bg-surface p-4 text-[12px] leading-relaxed text-muted">
          <div className="flex gap-2">
            <CircleAlert size={15} className="mt-0.5 shrink-0 text-warning" />
            <span>
              Sem os arquivos de carteiras simuladas, patrimônio, posições e curva não são reconstruídos. O painel não
              preenche lacunas com estimativas.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function aiTone(ai: AiStatus): "positive" | "neutral" | "warning" {
  if (ai.approved) return "positive";
  return ai.status === "DADOS_INSUFICIENTES" ? "neutral" : "warning";
}

function aiStatusLabel(ai: AiStatus): string {
  if (ai.approved) return "aprovada na trava";
  if (ai.status === "DADOS_INSUFICIENTES") return "só opina, sem prova ainda";
  if (ai.status === "REPROVADA") return "só opina, reprovada";
  return "só opina";
}

function AiCard({ ai, portfolios }: { ai: AiStatus; portfolios: PortfolioSummary[] }): ReactNode {
  const wallet = portfolios.find((item) => item.id === "IA");
  const hold = portfolios.find((item) => item.id === "SO_BTC");
  return (
    <Panel className="p-5 sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-faint">{ai.label}</div>
          <h2 className="mt-1 text-[18px] font-semibold text-ink">{ai.message}</h2>
        </div>
        <Badge tone={aiTone(ai)}>{aiStatusLabel(ai)}</Badge>
      </div>
      <div className="mt-5 grid gap-5 sm:grid-cols-3">
        <Stat label="Opinião de hoje" value={ai.picks || "sem previsão"} />
        <Stat label="Dias avaliados na trava" value={`${ai.n_days} de ${ai.min_days}`} />
        <Stat
          label="Carteira da IA contra só segurar BTC"
          value={
            wallet?.return_pct != null && hold?.return_pct != null
              ? `${pct(wallet.return_pct)} contra ${pct(hold.return_pct)}`
              : "sem placar publicado"
          }
        />
      </div>
      <p className="mt-4 text-[12px] leading-relaxed text-muted">
        A IA só passa a escolher as moedas do aporte simulado se a trava aprovar: pelo menos {ai.min_days} dias de previsões
        ao vivo, com ganho sobre o acaso já descontados os custos e o limite inferior do intervalo de 90% acima de zero.
        Dinheiro fictício, nenhuma ordem real é enviada.
      </p>
    </Panel>
  );
}

function PortfoliosBody({ data }: { data: PortfoliosData }): ReactNode {
  const params = useParams<{ portfolioId?: string }>();
  const navigate = useNavigate();
  const fallback = data.portfolios.find((portfolio) => portfolio.id === "DCA") ?? data.portfolios[0];
  const selected = data.portfolios.find((portfolio) => portfolio.id === params.portfolioId) ?? fallback;
  const detailQuery = usePortfolio(selected?.id ?? "");

  return (
    <div className="space-y-9">
      <PageHeader
        eyebrow="Carteiras"
        title="Capital simulado, sem atalhos."
        description="Cinco regras de alocação convivem aqui. Quatro dependem de arquivos de carteira que ainda não foram publicados; DCA aparece como referência do laboratório, não como carteira em reais."
        meta={
          <>
            <span>{data.portfolios.length} carteiras</span>
            <span>{data.data_available ? "dados simulados disponíveis" : "nenhuma carteira simulada disponível"}</span>
          </>
        }
        actions={<Badge tone="warning">sem ordens reais</Badge>}
      />

      {!data.data_available ? <InlineNote tone="warning">{data.note}</InlineNote> : null}

      {data.ai ? <AiCard ai={data.ai} portfolios={data.portfolios} /> : null}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {data.portfolios.map((portfolio) => (
          <PortfolioTile
            key={portfolio.id}
            portfolio={portfolio}
            selected={portfolio.id === selected?.id}
            onSelect={() => navigate(`/carteiras/${portfolio.id}`)}
          />
        ))}
      </section>

      {selected ? (
        <Panel className="p-5 sm:p-7">
          <Async<PortfolioDetail> query={detailQuery} loadingLabel="Carregando carteira">
            {(detail) => <DetailBody detail={detail} />}
          </Async>
        </Panel>
      ) : (
        <EmptyState
          icon={<WalletCards size={24} />}
          title="Nenhuma carteira configurada"
          description="A API não retornou carteiras para exibir."
        />
      )}
    </div>
  );
}

export function PortfoliosPage(): ReactNode {
  const query = usePortfolios();
  return <Async<PortfoliosData> query={query}>{(data) => <PortfoliosBody data={data} />}</Async>;
}
