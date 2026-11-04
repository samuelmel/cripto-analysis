import { ArrowUpRight, Search } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { CloseLineChart } from "../../components/charts/marketCharts";
import { Async } from "../../components/data-display/Async";
import { PageHeader } from "../../components/layout/PageHeader";
import { Badge, Button, InlineNote, Panel, SectionHeader, Stat } from "../../components/ui/primitives";
import {
  REGIME_LABEL,
  STAGE_LABEL,
  brl,
  dateShort,
  dateTime,
  number,
  pct,
  price,
  regimeTone,
  stageTone,
  toneForNumber,
} from "../../lib/format";
import type { AssetSummary, MarketData } from "../../schemas/api";
import { useMarket } from "../../services/queries";

function AssetTable({ assets }: { assets: readonly AssetSummary[] }): ReactNode {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] border-collapse text-left text-[12px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
            <th className="border-b border-hairline pb-2 pr-3 font-medium">Ativo</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Preço</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">7d</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">30d</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">90d</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Vol. 90d</th>
            <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Score</th>
            <th className="border-b border-hairline pb-2 pr-3 font-medium">Estágio</th>
            <th className="border-b border-hairline pb-2 text-right font-medium">Aporte</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((asset) => (
            <tr key={asset.symbol} className="group border-b border-hairline/70">
              <td className="py-2.5 pr-3">
                <Link to={`/mercado/${asset.base}`} className="font-medium text-ink group-hover:text-signal">
                  {asset.base}
                  <span className="ml-1.5 text-[10px] font-normal text-faint">/USDT</span>
                </Link>
                {asset.selected ? (
                  <span className="ml-2 inline-block size-1.5 rounded-full bg-signal align-middle" title="Selecionada para aporte" />
                ) : null}
              </td>
              <td className="num py-2.5 pr-3 text-right">{asset.close === null ? "—" : price(asset.close)}</td>
              <td className={`num py-2.5 pr-3 text-right ${toneForNumber(asset.ret_7d_pct)}`}>{pct(asset.ret_7d_pct)}</td>
              <td className={`num py-2.5 pr-3 text-right ${toneForNumber(asset.ret_30d_pct)}`}>{pct(asset.ret_30d_pct)}</td>
              <td className={`num py-2.5 pr-3 text-right ${toneForNumber(asset.ret_90d_pct)}`}>{pct(asset.ret_90d_pct)}</td>
              <td className="num py-2.5 pr-3 text-right text-muted">{pct(asset.vol_90d_pct)}</td>
              <td className="num py-2.5 pr-3 text-right">{number(asset.score, 1)}</td>
              <td className="py-2.5 pr-3">{asset.stage ? <Badge tone={stageTone(asset.stage)}>{STAGE_LABEL[asset.stage]}</Badge> : "—"}</td>
              <td className="num py-2.5 text-right">{asset.allocation_brl > 0 ? brl(asset.allocation_brl, 0) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MarketBody({ data }: { data: MarketData }): ReactNode {
  const [query, setQuery] = useState("");
  const [analysisOnly, setAnalysisOnly] = useState(true);
  const [limit, setLimit] = useState(40);
  const normalized = query.trim().toLowerCase();
  const allAssets = data.assets.filter((asset) => {
    if (analysisOnly && !asset.in_analysis) return false;
    if (!normalized) return true;
    return asset.symbol.toLowerCase().includes(normalized) || asset.name.toLowerCase().includes(normalized);
  });
  const visible = allAssets.slice(0, limit);
  const btcForecasts = data.forecasts.filter((forecast) => forecast.symbol === "BTC").slice(0, 4);
  const regimes = data.regime_history.slice(-12);
  const brief = data.brief;

  return (
    <div className="space-y-9">
      <PageHeader
        eyebrow="Ativos e mercado"
        title="Contexto antes da lista."
        description="Preços em USDT, sem conversão para reais. A tabela reúne o universo analisado e o histórico point-in-time disponível para cada ativo."
        meta={
          <>
            <span>{data.assets.length} ativos com preço</span>
            <span>atualizado em {dateTime(data.generated_at)}</span>
            <span>dados de {dateShort(brief.as_of)}</span>
          </>
        }
        actions={
          <Link
            to="/metodologia"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-hairline-strong bg-raised px-3 text-[13px] font-medium text-ink hover:bg-sunken"
          >
            Fontes e limites <ArrowUpRight size={14} />
          </Link>
        }
      />

      <section className="grid grid-cols-2 gap-x-5 gap-y-5 border-y border-hairline py-5 sm:grid-cols-3 xl:grid-cols-6">
        <Stat
          label="Regime"
          value={REGIME_LABEL[brief.regime]}
          note={brief.btc_distance_pct !== null ? `BTC ${pct(brief.btc_distance_pct)} vs SMA 200` : "sem leitura"}
          tone={regimeTone(brief.regime)}
          mono={false}
        />
        <Stat label="BTC" value={brief.btc_close === null ? "—" : price(brief.btc_close)} note={brief.btc_sma_200 === null ? "sem SMA 200" : `SMA ${price(brief.btc_sma_200)}`} />
        <Stat label="Fear & Greed" value={brief.fng_value ?? "—"} note={brief.fng_classification ?? "sem leitura"} />
        <Stat label="Acima da SMA 200" value={`${brief.breadth_up} / ${brief.breadth_down}`} note="acima / abaixo" />
        <Stat label="Analisadas" value={brief.n_analyzed} note={`${brief.n_selected} selecionadas`} />
        <Stat label="Aportes" value={brl(brief.total_allocated_brl, 0)} note="de R$ 100 simulados" />
      </section>

      <section>
        <SectionHeader
          eyebrow="BTC / USDT"
          title="Preço de fechamento"
          description="365 candles diários. A linha é fechamento, não média móvel nem preço intradiário."
          actions={
            <Link to="/mercado/BTC" className="inline-flex items-center gap-1 text-[12px] font-medium text-signal">
              Abrir BTC <ArrowUpRight size={13} />
            </Link>
          }
        />
        <div className="mt-4 border border-hairline bg-surface p-3 sm:p-4">
          <CloseLineChart candles={data.btc_candles} height={320} />
        </div>
      </section>

      <section>
        <SectionHeader
          eyebrow="Universo"
          title="Ativos monitorados"
          description="Score, tendência e aporte vêm da última execução. Use a busca para encontrar uma moeda específica."
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <label className="relative">
                <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
                <input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setLimit(40);
                  }}
                  placeholder="Buscar ativo"
                  aria-label="Buscar ativo"
                  className="h-9 w-44 rounded-md border border-hairline-strong bg-raised pl-8 pr-2 text-[12px] text-ink placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-signal"
                />
              </label>
              <Button variant={analysisOnly ? "primary" : "secondary"} onClick={() => setAnalysisOnly((value) => !value)}>
                {analysisOnly ? "Na análise" : "Todos"}
              </Button>
            </div>
          }
        />
        <div className="mt-4">
          {visible.length === 0 ? (
            <InlineNote>Nenhum ativo corresponde à busca.</InlineNote>
          ) : (
            <>
              <AssetTable assets={visible} />
              <div className="mt-4 flex items-center justify-between gap-3 text-[11px] text-faint">
                <span>
                  {visible.length} de {allAssets.length} ativos
                </span>
                {allAssets.length > visible.length ? (
                  <Button variant="secondary" onClick={() => setLimit((value) => value + 60)}>
                    Mostrar mais
                  </Button>
                ) : null}
              </div>
            </>
          )}
        </div>
      </section>

      <section className="grid gap-8 xl:grid-cols-[1.1fr_1fr]">
        <div className="min-w-0">
          <SectionHeader
            eyebrow="Regime"
            title="Últimos 12 dias"
            description="Distância da média e volatilidade classificam o contexto. O regime muda devagar."
          />
          <div className="mt-4 flex gap-1">
            {regimes.map((regime) => (
              <div
                key={regime.timestamp}
                title={`${dateShort(regime.timestamp)} · ${regime.trend_regime} · ${regime.vol_regime} · ${pct(regime.dist_ma_pct)}`}
                className={`h-14 flex-1 rounded-sm ${
                  regime.trend_regime.toLowerCase().includes("alta")
                    ? "bg-signal/70"
                    : regime.trend_regime.toLowerCase().includes("baixa")
                      ? "bg-critical/55"
                      : "bg-warning/45"
                }`}
              />
            ))}
          </div>
          <div className="mt-3 flex justify-between text-[10px] text-faint">
            <span>{dateShort(regimes[0]?.timestamp)}</span>
            <span>{dateShort(regimes.at(-1)?.timestamp)}</span>
          </div>
          <div className="mt-4 flex flex-wrap gap-3 text-[11px] text-muted">
            <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-sm bg-signal/70" /> tendência de alta</span>
            <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-sm bg-warning/45" /> lateral</span>
            <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-sm bg-critical/55" /> baixa</span>
          </div>
        </div>

        <div className="min-w-0">
          <SectionHeader
            eyebrow="Previsão"
            title="BTC em faixas"
            description="P10–P90 publicado. Nenhum modelo derrotou o baseline de forma consistente."
          />
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[420px] border-collapse text-left text-[12px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.13em] text-faint">
                  <th className="border-b border-hairline pb-2 pr-3 font-medium">Horizonte</th>
                  <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">P10</th>
                  <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">Mediana</th>
                  <th className="border-b border-hairline pb-2 pr-3 text-right font-medium">P90</th>
                  <th className="border-b border-hairline pb-2 text-right font-medium">Veredito</th>
                </tr>
              </thead>
              <tbody>
                {btcForecasts.map((forecast) => (
                  <tr key={`${forecast.horizon_days}-${forecast.role}`} className="border-b border-hairline/70">
                    <td className="py-2.5 pr-3">
                      <span className="text-ink">{forecast.horizon_days}d</span>
                      <span className="ml-2 text-[10px] uppercase tracking-[0.1em] text-faint">{forecast.role}</span>
                    </td>
                    <td className="num py-2.5 pr-3 text-right text-muted">{price(forecast.p10_price)}</td>
                    <td className="num py-2.5 pr-3 text-right text-ink">{price(forecast.p50_price)}</td>
                    <td className="num py-2.5 pr-3 text-right text-muted">{price(forecast.p90_price)}</td>
                    <td className="py-2.5 text-right">
                      <Badge tone={forecast.beats_baseline ? "warning" : "neutral"}>{forecast.verdict}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <Panel className="p-5">
        <SectionHeader eyebrow="Procedência" title="Saúde das fontes" description="Cada arquivo declara status, linhas e última data. Erros não são ocultados." />
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {data.sources.map((source) => (
            <div key={source.source} className="flex items-start justify-between gap-3 border-t border-hairline pt-3">
              <div className="min-w-0">
                <div className="text-[12px] font-medium text-ink">{source.source}</div>
                <div className="mt-0.5 text-[11px] text-muted">{source.scope}</div>
                <div className="mt-1 text-[10px] text-faint">
                  {source.rows} linhas · {source.last_data_ts ? dateShort(source.last_data_ts) : "sem data"}
                </div>
              </div>
              <Badge tone={source.status === "ok" ? "positive" : "critical"}>{source.status.toUpperCase()}</Badge>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

export function MarketPage(): ReactNode {
  const query = useMarket();
  return <Async<MarketData> query={query}>{(data) => <MarketBody data={data} />}</Async>;
}
