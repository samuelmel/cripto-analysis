import { ChartLineUp, Coins, Flask, Info, Scales, Wallet } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  changeOver,
  coinName,
  dataLagDays,
  fmt,
  fmtDateTime,
  fngLabel,
  fngTone,
  historyOf,
  lastCollection,
  modelForecast,
  notices,
  recentCloses,
  signalView,
  todayVerdict,
  type Tone,
} from "../data/analytics";
import { RECOMMENDED_SYMBOLS, coinFullName } from "../data/coins";
import { MissingFileError, loadDashboard } from "../data/loadSignals";
import type { Dashboard as Data } from "../types/signals";
import { CoinLogo } from "./CoinLabel";
import { ForecastView } from "./ForecastView";
import { GlossaryList } from "./Glossary";
import { Nav, panelId, tabId, type ViewId } from "./Nav";
import { CoinCard, ForecastBlock, NoticesArea, StatusStrip, type StripFacts } from "./Overview";
import { PositionsSection } from "./Positions";
import { PriceChart } from "./PriceChart";
import { RecommendationPanel, RecommendationStrip, SelectionView } from "./Recommendation";
import { LabPanel } from "./Research";
import { BacktestPanel, HowItWorks, MarketTable, TodayPanel, TradeList } from "./Sections";
import { Block, Section } from "./ui";

type State =
  | { readonly status: "loading" }
  | { readonly status: "missing" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly data: Data };

const ICON = 22;
const CORE: readonly string[] = [...RECOMMENDED_SYMBOLS];

export function Dashboard() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [view, setView] = useState<ViewId>("geral");

  /** Recarrega mantendo a tela atual até os dados novos chegarem (sem piscar). */
  const reload = useCallback(async (): Promise<void> => {
    try {
      setState({ status: "ready", data: await loadDashboard() });
    } catch (err) {
      if (err instanceof MissingFileError) setState({ status: "missing" });
      else setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="mx-auto max-w-[1120px] px-4 pt-10 pb-24 sm:px-8">
      <header>
        <h1 className="text-[28px] font-semibold tracking-[-0.01em]">Monitor de criptomoedas</h1>
        <p className="mt-1 text-muted">
          Quais moedas merecem um aporte hoje e quanto do seu orçamento, com os motivos e os riscos; a regra principal de Bitcoin e
          Ethereum; e o que fazer com o que você já comprou.
        </p>
        <Nav view={view} onChange={setView} />
      </header>
      <div className="mt-8">
        {state.status === "loading" && <p className="text-muted">Carregando os dados…</p>}
        {state.status === "missing" && (
          <Block>
            <p className="font-medium">Ainda não há dados para mostrar.</p>
            <p className="mt-2 text-muted">Rode o pipeline uma vez no terminal, na pasta do projeto, e recarregue a página:</p>
            <pre className="mt-3 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[13px]">uv run python -m src.pipeline</pre>
          </Block>
        )}
        {state.status === "error" && (
          <Block>
            <p className="font-medium text-critical">Não foi possível ler os dados.</p>
            <p className="mt-2 text-muted">{state.message}</p>
          </Block>
        )}
        {state.status === "ready" && <Ready data={state.data} view={view} onView={setView} onChanged={reload} />}
      </div>
    </div>
  );
}

function stripFacts(data: Data, now: Date): StripFacts {
  const btc = data.signals.find((s) => s.symbol === "BTC/USDT");
  const last = data.signals.reduce<Date | null>((m, s) => (m === null || s.timestamp > m ? s.timestamp : m), null);
  const lag = dataLagDays(last, now);
  const collected = lastCollection(data.sources);
  const reliable = btc !== undefined && btc.stage !== "INDISPONÍVEL";
  const up = btc?.regime_up === true;
  const marketTone: Tone = !reliable ? "warning" : up ? "good" : "critical";
  const staleText = lag === null ? "Sem dados" : lag <= 0 ? "Dados em dia" : `Dados com ${lag} ${lag === 1 ? "dia" : "dias"} de atraso`;
  const failText = collected.failures > 0 ? `, ${collected.failures} ${collected.failures === 1 ? "falha" : "falhas"} de coleta` : "";
  return {
    marketText: !reliable ? "Sem dados confiáveis" : up ? "Em alta" : "Em baixa",
    marketTone,
    marketNote: !reliable ? "none" : up ? "up" : "down",
    collectedAt: collected.at === null ? "Sem registro de coleta" : fmtDateTime(collected.at),
    freshness: collected.at === null ? `${staleText}. Rode o pipeline sem --offline para registrar a coleta` : `${staleText}${failText}`,
    freshnessTone: collected.failures > 0 ? "critical" : collected.at === null ? "neutral" : lag !== null && lag <= 0 ? "good" : "warning",
    analysisDay: fmt.day(last),
  };
}

function Ready({ data, view, onView, onChanged }: {
  readonly data: Data;
  readonly view: ViewId;
  readonly onView: (id: ViewId) => void;
  readonly onChanged: () => Promise<void>;
}) {
  const { signals, recommendation, selectionPerf, history, trades, forecast, sources, lab, performance, positions, closed } = data;
  const first = signals[0];
  const [selected, setSelected] = useState<string>(positions[0]?.symbol ?? "BTC/USDT");
  const [showForecast, setShowForecast] = useState(true);
  const now = useMemo(() => new Date(), []);

  const verdict = useMemo(() => todayVerdict(signals, positions), [signals, positions]);
  const facts = useMemo(() => stripFacts(data, now), [data, now]);
  const lag = useMemo(
    () => dataLagDays(signals.reduce<Date | null>((m, s) => (m === null || s.timestamp > m ? s.timestamp : m), null), now),
    [signals, now],
  );
  const warnings = useMemo(() => notices(signals, sources, lag), [signals, sources, lag]);
  const core = useMemo(() => CORE.flatMap((symbol) => signals.filter((s) => s.symbol === symbol)), [signals]);
  const chartHistory = useMemo(() => historyOf(history, selected), [history, selected]);
  const chartTrades = useMemo(() => trades.filter((t) => t.symbol === selected), [trades, selected]);
  const chartPositions = useMemo(() => positions.filter((p) => p.symbol === selected), [positions, selected]);
  const chartForecast = useMemo(() => modelForecast(forecast, selected), [forecast, selected]);
  const coinsByName = useMemo(() => signals.toSorted((a, b) => a.symbol.localeCompare(b.symbol)), [signals]);
  const sparks = useMemo(
    () => new Map(signals.map((s) => [s.symbol, recentCloses(history, s.symbol)] as const)),
    [signals, history],
  );
  const coin = coinName(selected);

  const chart = (withForecast: boolean) => (
    <Block>
      {withForecast && chartForecast.length > 0 && (
        <label className="mb-3 flex items-center gap-2 text-[14px]">
          <input type="checkbox" checked={showForecast} onChange={(e) => setShowForecast(e.target.checked)} />
          Mostrar a faixa de previsão (estimativa)
        </label>
      )}
      <PriceChart
        history={chartHistory}
        trades={chartTrades}
        positions={chartPositions}
        forecast={withForecast ? chartForecast : []}
        showForecast={withForecast && showForecast}
      />
    </Block>
  );

  return (
    <main>
      <div role="tabpanel" id={panelId("geral")} aria-labelledby={tabId("geral")} hidden={view !== "geral"}>
        <div className="space-y-6">
          <RecommendationStrip rec={recommendation} now={now} />
          <NoticesArea items={warnings} />
          <RecommendationPanel
            signals={signals}
            rec={recommendation}
            onDetails={() => {
              onView("selecao");
              window.scrollTo({ top: 0 });
            }}
          />
        </div>
        <div className="mt-16 space-y-6">
          <div>
            <h2 className="text-lg font-semibold">Regra principal: média de 200 dias (Bitcoin e Ethereum)</h2>
            <p className="mt-1 max-w-[72ch] text-muted">
              A referência original do painel, preservada. Ela diz se BTC e ETH estão em tendência de alta e quando vender o
              que você já tem. O aporte de cima vem da seleção, que também avalia risco, liquidez e preço esticado.
            </p>
          </div>
          <StatusStrip facts={facts} />
          <TodayPanel
            verdict={verdict}
            fng={first?.fng_value ?? null}
            fngText={fngLabel(first?.fng_classification ?? null)}
            fngTone={fngTone(first?.fng_value ?? null)}
            asOf={fmt.day(first?.timestamp ?? null)}
          />
          <div className="grid gap-6 md:grid-cols-2">
            {core.map((s) => (
              <CoinCard
                key={s.symbol}
                signal={s}
                view={signalView(s)}
                change1={changeOver(history, s.symbol, 1)}
                change30={changeOver(history, s.symbol, 30)}
                closes={sparks.get(s.symbol) ?? []}
                selected={s.symbol === selected}
                onSelect={setSelected}
              />
            ))}
          </div>
          <ForecastBlock forecast={forecast} symbols={CORE} />
          <section aria-labelledby="grafico">
            <h2 id="grafico" className="mb-4 flex items-center gap-3 text-lg font-semibold">
              <CoinLogo symbol={selected} size={28} />
              Gráfico de {coinFullName(selected)}
              <ChartLineUp size={ICON} className="text-muted" aria-hidden />
            </h2>
            {chart(true)}
          </section>
        </div>
        <div className="mt-16">
          <Section
            id="posicoes"
            title="Suas posições"
            icon={<Wallet size={ICON} aria-hidden />}
            lead="Registre aqui o que você comprou. O painel acompanha cada compra e avisa quando for hora de vender."
          >
            <PositionsSection positions={positions} closed={closed} coins={coinsByName} onChanged={onChanged} />
          </Section>
        </div>
      </div>

      <div role="tabpanel" id={panelId("selecao")} aria-labelledby={tabId("selecao")} hidden={view !== "selecao"}>
        <SelectionView signals={signals} rec={recommendation} perf={selectionPerf} />
      </div>

      <div role="tabpanel" id={panelId("historico")} aria-labelledby={tabId("historico")} hidden={view !== "historico"}>
        <Section
          id="moedas"
          title="Todas as moedas"
          icon={<Coins size={ICON} aria-hidden />}
          lead="O que a regra principal (média de 200 dias) diz de cada moeda. O sinal de compra dela vale só para Bitcoin e Ethereum; o aporte em qualquer moeda vem da aba Seleção. Clique numa moeda para ver o gráfico e o histórico dela."
        >
          <MarketTable rows={signals} recommended={RECOMMENDED_SYMBOLS} sparks={sparks} selected={selected} onSelect={setSelected} />
        </Section>
        <section aria-labelledby="detalhe" className="mt-16">
          <h2 id="detalhe" className="flex items-center gap-3 text-lg font-semibold">
            <CoinLogo symbol={selected} size={28} />
            {coinFullName(selected)} ({coin}) desde {fmt.day(chartHistory[0]?.timestamp ?? null)}
          </h2>
          <div className="mt-5">{chart(false)}</div>
          <h3 className="mt-8 font-medium">Cada período em que a regra mandou comprar ou segurar {coin}</h3>
          <div className="mt-3">
            <TradeList trades={chartTrades} coin={coin} recommended={RECOMMENDED_SYMBOLS.has(selected)} />
          </div>
        </section>
      </div>

      <div role="tabpanel" id={panelId("previsoes")} aria-labelledby={tabId("previsoes")} hidden={view !== "previsoes"}>
        {forecast.length === 0 ? (
          <Block>
            <p className="font-medium">Ainda não há previsão para mostrar.</p>
            <p className="mt-2 text-muted">O pipeline gera a previsão junto com a análise. Rode no terminal e recarregue a página:</p>
            <pre className="mt-3 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[13px]">uv run python -m src.pipeline --offline</pre>
          </Block>
        ) : (
          <ForecastView forecast={forecast} symbols={CORE} history={history} trades={trades} positions={positions} />
        )}
      </div>

      <div role="tabpanel" id={panelId("pesquisa")} aria-labelledby={tabId("pesquisa")} hidden={view !== "pesquisa"}>
        <Section id="funciona" title="A regra de compra funciona?" icon={<Scales size={ICON} aria-hidden />}>
          <BacktestPanel performance={performance} trades={trades} />
        </Section>
        <div className="mt-16">
          <Section
            id="laboratorio"
            title="Laboratório de estratégias"
            icon={<Flask size={ICON} aria-hidden />}
            lead="Outras ideias testadas com o mesmo motor da regra do painel. Os resultados mostram também o que perdeu."
          >
            <LabPanel rows={lab} />
          </Section>
        </div>
        <div className="mt-16">
          <Section id="como" title="Como funciona" icon={<Info size={ICON} aria-hidden />}>
            <HowItWorks />
          </Section>
        </div>
        <div className="mt-16">
          <Section id="glossario" title="Glossário" lead="Os termos do painel em português simples. Nos cartões, passe o mouse sobre o termo sublinhado.">
            <GlossaryList />
          </Section>
        </div>
      </div>
    </main>
  );
}
