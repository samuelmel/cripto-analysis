import { ArrowsClockwise } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  coinName,
  dataLagDays,
  fmt,
  fmtDateTime,
  historyOf,
  lastCollection,
  modelForecast,
  recentCloses,
  type Tone,
} from "../data/analytics";
import { RECOMMENDED_SYMBOLS, coinFullName } from "../data/coins";
import { MissingFileError, loadDashboard } from "../data/loadSignals";
import { simpleNotices, todaySummary } from "../data/today";
import type { Dashboard as Data } from "../types/signals";
import { CoinLogo } from "./CoinLabel";
import { ForecastView } from "./ForecastView";
import { Nav, panelId, tabId, type ViewId } from "./Nav";
import { PriceChart } from "./PriceChart";
import { SelectionView } from "./Recommendation";
import { ResearchView } from "./ResearchView";
import { MarketTable, TradeList } from "./Sections";
import { TodayView } from "./Today";
import { Empty, Panel, TEXT_TONE } from "./ui";

type State =
  | { readonly status: "loading" }
  | { readonly status: "missing" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly data: Data };

const CORE: readonly string[] = [...RECOMMENDED_SYMBOLS];

/* ---------- barra superior: nome, abas e estado dos dados ---------- */

interface Freshness {
  readonly closeDay: string;
  readonly freshness: string;
  readonly freshnessTone: Tone;
  readonly collectedAt: string;
  readonly runState: string;
  readonly runTone: Tone;
}

function freshnessOf(data: Data, now: Date): Freshness {
  const last = data.signals.reduce<Date | null>((m, s) => (m === null || s.timestamp > m ? s.timestamp : m), null);
  const lag = dataLagDays(last, now);
  const collected = lastCollection(data.sources);
  const failed = collected.failures > 0;
  const status = data.recommendation.data_status;
  return {
    closeDay: fmt.day(last),
    freshness: lag === null ? "sem dados" : lag <= 0 ? "em dia" : `${lag} ${lag === 1 ? "dia" : "dias"} de atraso`,
    freshnessTone: lag === null ? "critical" : lag <= 0 ? "good" : "warning",
    collectedAt: collected.at === null ? "sem registro de coleta" : fmtDateTime(collected.at),
    runState: failed
      ? `${collected.failures} ${collected.failures === 1 ? "falha" : "falhas"} de coleta`
      : status === "OK" ? "OK" : status === "PARCIAL" ? "dados parciais" : "dados indisponíveis",
    runTone: failed ? "critical" : status === "OK" ? "good" : "warning",
  };
}

function TopBar({ view, onView, fresh, onReload, reloading }: {
  readonly view: ViewId;
  readonly onView: (v: ViewId) => void;
  readonly fresh: Freshness | null;
  readonly onReload: () => void;
  readonly reloading: boolean;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-hairline bg-surface">
      <div className="mx-auto flex max-w-[1760px] flex-wrap items-center gap-x-5 gap-y-1 px-3 py-1.5 sm:px-4">
        <h1 className="flex items-baseline gap-2 whitespace-nowrap">
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Crypto Analyzer</span>
          <span className="hidden text-[12px] text-muted lg:inline">o que fazer com cripto hoje</span>
        </h1>
        <Nav view={view} onChange={onView} />
        {fresh !== null && (
          <dl className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-0.5 text-[12px]">
            <div className="flex gap-1" title={`Coleta: ${fresh.collectedAt} · última execução: ${fresh.runState}`}>
              <dt className="text-muted">Dados de</dt>
              <dd className="num font-medium">{fresh.closeDay}</dd>
              <dd className={TEXT_TONE[fresh.freshnessTone]}>({fresh.freshness})</dd>
            </div>
            <button
              type="button"
              onClick={onReload}
              disabled={reloading}
              aria-label="Recarregar os dados publicados"
              title="Recarrega os arquivos publicados pelo pipeline (não roda o pipeline)"
              className="flex items-center gap-1 rounded-sm border border-hairline px-2 py-1 text-muted hover:bg-ground hover:text-ink disabled:opacity-50"
            >
              <ArrowsClockwise size={14} aria-hidden /> Recarregar
            </button>
          </dl>
        )}
      </div>
    </header>
  );
}

/* ---------- aplicativo ---------- */

export function Dashboard() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [view, setView] = useState<ViewId>("geral");
  const [reloading, setReloading] = useState(false);
  const now = useMemo(() => new Date(), []);

  /** Recarrega mantendo a tela atual até os dados novos chegarem (sem piscar). */
  const reload = useCallback(async (): Promise<void> => {
    setReloading(true);
    try {
      setState({ status: "ready", data: await loadDashboard() });
    } catch (err) {
      if (err instanceof MissingFileError) setState({ status: "missing" });
      else setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
    } finally {
      setReloading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const fresh = useMemo(() => (state.status === "ready" ? freshnessOf(state.data, now) : null), [state, now]);

  return (
    <div className="min-h-screen">
      <TopBar view={view} onView={setView} fresh={fresh} onReload={() => void reload()} reloading={reloading} />
      <div className="mx-auto max-w-[1760px] px-3 pb-10 pt-3 sm:px-4">
        {state.status === "loading" && (
          <div role="status" aria-live="polite" className="space-y-3">
            <p className="text-muted">Carregando os dados publicados…</p>
            <div aria-hidden className="h-[180px] rounded-md border border-hairline bg-surface" />
            <div aria-hidden className="h-[240px] rounded-md border border-hairline bg-surface" />
          </div>
        )}
        {state.status === "missing" && (
          <Panel id="sem-dados" title="Ainda não há dados para mostrar">
            <p className="text-muted">Rode o pipeline uma vez no terminal, na pasta do projeto, e recarregue a página:</p>
            <pre className="mt-2 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[12px]">uv run python -m src.pipeline</pre>
          </Panel>
        )}
        {state.status === "error" && (
          <Panel id="erro" title="Não foi possível ler os dados">
            <p className="font-medium text-critical">{state.message}</p>
            <p className="mt-1 text-muted">Confira se o pipeline terminou sem erro e recarregue.</p>
          </Panel>
        )}
        {state.status === "ready" && <Ready data={state.data} view={view} onView={setView} onChanged={reload} now={now} />}
      </div>
    </div>
  );
}

function Ready({ data, view, onView, onChanged, now }: {
  readonly data: Data;
  readonly view: ViewId;
  readonly onView: (id: ViewId) => void;
  readonly onChanged: () => Promise<void>;
  readonly now: Date;
}) {
  const { signals, recommendation, selectionPerf, history, trades, forecast, sources, positions, closed, positionStates } = data;
  const [selected, setSelected] = useState<string>(positions[0]?.symbol ?? "BTC/USDT");

  const summary = useMemo(() => todaySummary(data), [data]);
  const lag = useMemo(
    () => dataLagDays(signals.reduce<Date | null>((m, s) => (m === null || s.timestamp > m ? s.timestamp : m), null), now),
    [signals, now],
  );
  const warnings = useMemo(() => simpleNotices(signals, sources, lag), [signals, sources, lag]);
  const chartHistory = useMemo(() => historyOf(history, selected), [history, selected]);
  const chartTrades = useMemo(() => trades.filter((t) => t.symbol === selected), [trades, selected]);
  const chartPositions = useMemo(() => positions.filter((p) => p.symbol === selected), [positions, selected]);
  const chartForecast = useMemo(() => modelForecast(forecast, selected), [forecast, selected]);
  const coinsByName = useMemo(() => signals.toSorted((a, b) => a.symbol.localeCompare(b.symbol)), [signals]);
  const sparks = useMemo(() => new Map(signals.map((s) => [s.symbol, recentCloses(history, s.symbol)] as const)), [signals, history]);
  const coin = coinName(selected);

  return (
    <main className="space-y-3">
      <div role="tabpanel" id={panelId("geral")} aria-labelledby={tabId("geral")} hidden={view !== "geral"}>
        <TodayView
          summary={summary}
          notices={warnings}
          signals={signals}
          recommendation={recommendation}
          hasLevels={data.entryLevels.length > 0}
          selected={selected}
          onSelect={setSelected}
          coinsByName={coinsByName}
          sparks={sparks}
          chartHistory={chartHistory}
          chartTrades={chartTrades}
          chartPositions={chartPositions}
          chartForecast={chartForecast}
          positions={positions}
          closed={closed}
          positionStates={positionStates}
          onDetails={() => {
            onView("selecao");
            window.scrollTo({ top: 0 });
          }}
          onChanged={onChanged}
        />
      </div>

      <div role="tabpanel" id={panelId("selecao")} aria-labelledby={tabId("selecao")} hidden={view !== "selecao"}>
        <SelectionView signals={signals} rec={recommendation} perf={selectionPerf} />
      </div>

      <div role="tabpanel" id={panelId("historico")} aria-labelledby={tabId("historico")} hidden={view !== "historico"}>
        <div className="grid items-start gap-3 lg:grid-cols-12">
          <Panel
            id="moedas-hist"
            title="Todas as moedas"
            note="clique para ver o gráfico e o histórico; o sinal de compra da regra vale só para BTC e ETH"
            className="lg:col-span-6"
            bodyClassName="p-0"
          >
            <MarketTable rows={signals} recommended={RECOMMENDED_SYMBOLS} sparks={sparks} selected={selected} onSelect={setSelected} maxHeight="max-h-[640px]" />
          </Panel>
          <div className="min-w-0 space-y-3 lg:col-span-6">
            <Panel
              id="detalhe"
              title={
                <span className="flex items-center gap-2">
                  <CoinLogo symbol={selected} size={18} />
                  {coinFullName(selected)} ({coin})
                  <span className="font-normal text-muted">desde {fmt.day(chartHistory[0]?.timestamp ?? null)}</span>
                </span>
              }
            >
              {chartHistory.length === 0 ? (
                <Empty title="Sem histórico de preço para esta moeda" />
              ) : (
                <PriceChart history={chartHistory} trades={chartTrades} positions={chartPositions} forecast={[]} showForecast={false} height={320} />
              )}
            </Panel>
            <Panel id="operacoes" title={`Cada período em que a regra mandou comprar ou segurar ${coin}`} bodyClassName="p-0">
              <TradeList trades={chartTrades} coin={coin} recommended={RECOMMENDED_SYMBOLS.has(selected)} maxHeight="max-h-[260px]" />
            </Panel>
          </div>
        </div>
      </div>

      <div role="tabpanel" id={panelId("previsoes")} aria-labelledby={tabId("previsoes")} hidden={view !== "previsoes"}>
        {forecast.length === 0 ? (
          <Panel id="sem-previsao" title="Previsões">
            <Empty title="Ainda não há previsão para mostrar.">
              O pipeline gera a previsão junto com a análise. Rode no terminal e recarregue a página:
              <pre className="mt-2 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[12px] text-ink">uv run python -m src.pipeline --offline</pre>
            </Empty>
          </Panel>
        ) : (
          <ForecastView forecast={forecast} symbols={CORE} history={history} trades={trades} positions={positions} />
        )}
      </div>

      <div role="tabpanel" id={panelId("pesquisa")} aria-labelledby={tabId("pesquisa")} hidden={view !== "pesquisa"}>
        <ResearchView data={data} />
      </div>
    </main>
  );
}
