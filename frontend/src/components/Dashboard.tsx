import { useEffect, useMemo, useState } from "react";
import {
  allByZscore,
  byStrategy,
  coinName,
  fmt,
  fngLabel,
  fngTone,
  historyOf,
  todayVerdict,
} from "../data/analytics";
import { MissingFileError, loadDashboard } from "../data/loadSignals";
import type { Dashboard as Data } from "../types/signals";
import { PriceChart } from "./PriceChart";
import { BacktestPanel, HowItWorks, MarketTable, PositionsTable, TodayPanel, TradeList } from "./Sections";
import { Block, Section } from "./ui";

type State =
  | { readonly status: "loading" }
  | { readonly status: "missing" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly data: Data };

export function Dashboard() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let alive = true;
    loadDashboard()
      .then((data) => {
        if (alive) setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (!alive) return;
        if (err instanceof MissingFileError) setState({ status: "missing" });
        else setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="mx-auto max-w-[1120px] px-4 pt-10 pb-24 sm:px-8">
      <header className="mb-10">
        <h1 className="text-[28px] font-semibold tracking-[-0.01em]">Monitor de criptomoedas</h1>
        <p className="mt-1 text-muted">O que fazer hoje com as 15 maiores moedas, e com as que você já comprou.</p>
      </header>
      {state.status === "loading" && <p className="text-muted">Carregando os dados…</p>}
      {state.status === "missing" && (
        <Block>
          <p className="font-medium">Ainda não há dados para mostrar.</p>
          <p className="mt-2 text-muted">Rode o pipeline uma vez no terminal, na pasta do projeto, e recarregue a página:</p>
          <pre className="mt-3 rounded-sm bg-ground px-3 py-2 text-[13px]">uv run python -m src.pipeline</pre>
        </Block>
      )}
      {state.status === "error" && (
        <Block>
          <p className="font-medium text-critical">Não foi possível ler os dados.</p>
          <p className="mt-2 text-muted">{state.message}</p>
        </Block>
      )}
      {state.status === "ready" && <Ready data={state.data} />}
    </div>
  );
}

function Ready({ data }: { readonly data: Data }) {
  const { signals, history, trades, positions } = data;
  const first = signals[0];
  const [selected, setSelected] = useState<string>(positions[0]?.symbol ?? "BTC/USDT");

  const verdict = useMemo(() => todayVerdict(signals, positions), [signals, positions]);
  const signalTrades = useMemo(() => byStrategy(trades, "SINAL"), [trades]);
  const referenceTrades = useMemo(() => byStrategy(trades, "REFERENCIA"), [trades]);
  const chartHistory = useMemo(() => historyOf(history, selected), [history, selected]);
  const chartTrades = useMemo(() => signalTrades.filter((t) => t.symbol === selected), [signalTrades, selected]);
  const chartPositions = useMemo(() => positions.filter((p) => p.symbol === selected), [positions, selected]);
  const market = useMemo(() => allByZscore(signals), [signals]);
  const since = useMemo(
    () => history.reduce<Date | null>((m, h) => (m === null || h.timestamp < m ? h.timestamp : m), null),
    [history],
  );
  const coin = coinName(selected);

  return (
    <main>
      <TodayPanel
        verdict={verdict}
        fng={first?.fng_value ?? null}
        fngText={fngLabel(first?.fng_classification ?? null)}
        fngTone={fngTone(first?.fng_value ?? null)}
        asOf={fmt.day(first?.timestamp ?? null)}
      />

      <Section id="posicoes" title="Suas posições" lead="Cada compra que você registrou, quanto está rendendo e se é hora de vender.">
        <PositionsTable positions={positions} />
      </Section>

      <Section
        id="moedas"
        title="Todas as moedas"
        lead="Da mais barata em relação ao normal para a mais cara. Clique numa moeda para ver o gráfico e o histórico dela."
      >
        <MarketTable rows={market} selected={selected} onSelect={setSelected} />
      </Section>

      <Section id="detalhe" title={`${coin} desde ${fmt.day(chartHistory[0]?.timestamp ?? null)}`}>
        <Block>
          <PriceChart history={chartHistory} trades={chartTrades} positions={chartPositions} />
        </Block>
        <h3 className="mt-8 font-medium">Cada vez que o sinal de compra disparou para {coin}</h3>
        <div className="mt-3">
          <TradeList trades={chartTrades} coin={coin} />
        </div>
      </Section>

      <Section id="funciona" title="A regra de compra funciona?">
        <BacktestPanel signal={signalTrades} reference={referenceTrades} since={fmt.day(since)} />
      </Section>

      <Section id="como" title="Como funciona">
        <HowItWorks />
      </Section>
    </main>
  );
}
