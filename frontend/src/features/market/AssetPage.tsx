import { ArrowLeft, CircleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { CloseLineChart } from "../../components/charts/marketCharts";
import { Async } from "../../components/data-display/Async";
import { PageHeader } from "../../components/layout/PageHeader";
import { SegmentedTabs } from "../../components/ui/tabs";
import { Badge, EmptyState, InlineNote, Panel, SectionHeader, Stat } from "../../components/ui/primitives";
import {
  OPPORTUNITY_LABEL,
  STAGE_LABEL,
  brl,
  dateShort,
  entryLabel,
  number,
  opportunityTone,
  pct,
  price,
  stageTone,
  toneForNumber,
} from "../../lib/format";
import type { AssetDetail } from "../../schemas/api";
import { useAsset } from "../../services/queries";

const WINDOWS = [
  { value: "30", label: "30d" },
  { value: "90", label: "90d" },
  { value: "365", label: "1 ano" },
] as const;

function AssetBody({ asset }: { asset: AssetDetail }): ReactNode {
  const analysis = asset.analysis;
  return (
    <div className="space-y-9">
      <PageHeader
        eyebrow={`${asset.base} / USDT`}
        title={asset.name}
        description={analysis?.stage_reason ?? "Sem leitura de análise para este ativo na data de referência."}
        meta={
          <>
            <span>{asset.rows} candles no histórico</span>
            <span>{asset.first_date ? `desde ${dateShort(asset.first_date)}` : "sem início"}</span>
            <span>{asset.last_date ? `até ${dateShort(asset.last_date)}` : "sem fim"}</span>
            <span>fonte {asset.source}</span>
          </>
        }
        actions={
          <Link
            to="/mercado"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-hairline-strong bg-raised px-3 text-[13px] font-medium text-ink hover:bg-sunken"
          >
            <ArrowLeft size={14} /> Mercado
          </Link>
        }
      />

      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Fechamento" value={price(asset.candles.at(-1)?.close)} note={asset.last_date ? dateShort(asset.last_date) : "—"} />
        <Stat label="Score" value={analysis ? number(analysis.score, 1) : "—"} note={analysis ? `${analysis.conditions_met}/${analysis.conditions_total} condições` : "sem análise"} />
        <Stat
          label="Estágio"
          value={analysis ? STAGE_LABEL[analysis.stage] : "—"}
          note={analysis ? OPPORTUNITY_LABEL[analysis.opportunity] : "sem leitura"}
          tone={analysis ? (analysis.stage === "COMPRAR" ? "positive" : analysis.stage === "INDISPONÍVEL" ? "warning" : "neutral") : "neutral"}
          mono={false}
        />
        <Stat label="Aporte" value={analysis && analysis.allocation_brl > 0 ? brl(analysis.allocation_brl, 0) : "—"} note={analysis ? `peso ${pct(analysis.target_fraction * 100)}` : "fora da seleção"} />
      </div>

      <section>
        <SectionHeader
          eyebrow="Preço"
          title="Fechamento diário"
          description={`${asset.candles.length} candles na janela. A série completa tem ${asset.rows} linhas point-in-time.`}
        />
        <div className="mt-4 border border-hairline bg-surface p-3 sm:p-4">
          <CloseLineChart candles={asset.candles} height={340} color="#0d6b63" />
        </div>
      </section>

      <div className="grid gap-8 xl:grid-cols-[1.2fr_1fr]">
        <section>
          <SectionHeader eyebrow="Análise" title="Por que entrou ou ficou de fora" />
          {!analysis ? (
            <div className="mt-4">
              <EmptyState title="Sem análise publicada" description={asset.eligibility_note} />
            </div>
          ) : (
            <Panel className="mt-4 p-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={stageTone(analysis.stage)}>{STAGE_LABEL[analysis.stage]}</Badge>
                <Badge tone={opportunityTone(analysis.opportunity)}>{OPPORTUNITY_LABEL[analysis.opportunity]}</Badge>
                <Badge tone={analysis.entry_level === "PROMISSOR" ? "warning" : "neutral"}>{entryLabel(analysis.entry_level)}</Badge>
                {analysis.selected ? <Badge tone="positive">selecionada</Badge> : null}
              </div>
              <div className="mt-5 grid grid-cols-2 gap-x-5 gap-y-4 border-t border-hairline pt-4 sm:grid-cols-3">
                <Stat label="RSI 14" value={number(analysis.rsi_14, 1)} />
                <Stat label="Vol. 90d" value={pct(analysis.vol_90d_pct)} />
                <Stat label="Queda atual" value={pct(analysis.drawdown_now_pct)} />
                <Stat label="SMA 50" value={analysis.sma_50 === null ? "—" : price(analysis.sma_50)} />
                <Stat label="SMA 90" value={analysis.sma_90 === null ? "—" : price(analysis.sma_90)} />
                <Stat label="SMA 200" value={analysis.sma_200 === null ? "—" : price(analysis.sma_200)} />
              </div>
              <div className="mt-5 grid gap-5 border-t border-hairline pt-4 sm:grid-cols-3">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.13em] text-faint">7 dias</div>
                  <div className={`num mt-1 text-[15px] ${toneForNumber(analysis.ret_7d_pct)}`}>{pct(analysis.ret_7d_pct)}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-[0.13em] text-faint">30 dias</div>
                  <div className={`num mt-1 text-[15px] ${toneForNumber(analysis.ret_30d_pct)}`}>{pct(analysis.ret_30d_pct)}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-[0.13em] text-faint">90 dias</div>
                  <div className={`num mt-1 text-[15px] ${toneForNumber(analysis.ret_90d_pct)}`}>{pct(analysis.ret_90d_pct)}</div>
                </div>
              </div>
            </Panel>
          )}
        </section>

        <section>
          <SectionHeader eyebrow="Tese" title="Razões, riscos e bloqueios" />
          <div className="mt-4 space-y-4">
            <ReasonList title="Razões" items={analysis?.reasons ?? []} tone="positive" empty="Nenhuma razão registrada." />
            <ReasonList title="Riscos" items={analysis?.risks ?? []} tone="warning" empty="Nenhum risco registrado." />
            <ReasonList title="Bloqueios" items={analysis?.blockers ?? []} tone="critical" empty="Nenhum bloqueio registrado." />
          </div>
          <div className="mt-5">
            <InlineNote tone="neutral">{asset.universe_note}</InlineNote>
          </div>
          <div className="mt-3">
            <InlineNote tone="warning">{asset.eligibility_note}</InlineNote>
          </div>
        </section>
      </div>
    </div>
  );
}

function ReasonList({
  title,
  items,
  tone,
  empty,
}: {
  title: string;
  items: readonly string[];
  tone: "positive" | "warning" | "critical";
  empty: string;
}): ReactNode {
  const dot = tone === "positive" ? "bg-good" : tone === "warning" ? "bg-warning" : "bg-critical";
  return (
    <div>
      <div className="flex items-center gap-2">
        <CircleAlert size={13} className="text-faint" />
        <h3 className="text-[11px] font-medium uppercase tracking-[0.13em] text-faint">{title}</h3>
      </div>
      {items.length === 0 ? (
        <p className="mt-2 text-[12px] text-faint">{empty}</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {items.map((item) => (
            <li key={item} className="flex gap-2 text-[12px] leading-relaxed text-muted">
              <span className={`mt-1.5 size-1 shrink-0 rounded-full ${dot}`} />
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssetQuery({ symbol }: { symbol: string }): ReactNode {
  const [days, setDays] = useState<"30" | "90" | "365">("365");
  const query = useAsset(symbol, Number(days));
  return (
    <div>
      <div className="mb-4 flex justify-end">
        <SegmentedTabs
          value={days}
          onValueChange={(value) => setDays(value as "30" | "90" | "365")}
          options={WINDOWS}
          label="Janela do gráfico"
        />
      </div>
      <Async<AssetDetail> query={query} loadingLabel={`Carregando ${symbol}`}>
        {(asset) => <AssetBody asset={asset} />}
      </Async>
    </div>
  );
}

export function AssetPage(): ReactNode {
  const { symbol } = useParams<{ symbol: string }>();
  const clean = (symbol ?? "").replace("/USDT", "").toUpperCase();
  if (!clean) {
    return (
      <EmptyState
        title="Ativo não informado"
        description="Escolha uma moeda na página de mercado."
        action={
          <Link to="/mercado" className="inline-flex items-center gap-1 text-[12px] font-medium text-signal">
            <ArrowLeft size={13} /> Voltar
          </Link>
        }
      />
    );
  }
  return <AssetQuery symbol={clean} />;
}
