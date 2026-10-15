import { ChartLineUp, Coins, Info, Scales, Wallet } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  coinName,
  fmt,
  fngLabel,
  fngTone,
  historyOf,
  recentCloses,
  todayVerdict,
} from "../data/analytics";
import { RECOMMENDED_SYMBOLS, coinFullName } from "../data/coins";
import { MissingFileError, loadDashboard } from "../data/loadSignals";
import type { Dashboard as Data } from "../types/signals";
import { CoinLogo } from "./CoinLabel";
import { PositionsSection } from "./Positions";
import { PriceChart } from "./PriceChart";
import { BacktestPanel, HowItWorks, MarketTable, TodayPanel, TradeList } from "./Sections";
import { Block, Section } from "./ui";

type State =
  | { readonly status: "loading" }
  | { readonly status: "missing" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly data: Data };

const ICON = 22;

export function Dashboard() {
  const [state, setState] = useState<State>({ status: "loading" });

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
      <header className="mb-10">
        <h1 className="text-[28px] font-semibold tracking-[-0.01em]">Monitor de criptomoedas</h1>
        <p className="mt-1 text-muted">O que fazer hoje com Bitcoin e Ethereum, o que acontece com as outras 13 maiores moedas, e com o que você já comprou.</p>
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
      {state.status === "ready" && <Ready data={state.data} onChanged={reload} />}
    </div>
  );
}

function Ready({ data, onChanged }: { readonly data: Data; readonly onChanged: () => Promise<void> }) {
  const { signals, history, trades, performance, positions, closed } = data;
  const first = signals[0];
  const [selected, setSelected] = useState<string>(positions[0]?.symbol ?? "BTC/USDT");

  const verdict = useMemo(() => todayVerdict(signals, positions), [signals, positions]);
  const chartHistory = useMemo(() => historyOf(history, selected), [history, selected]);
  const chartTrades = useMemo(() => trades.filter((t) => t.symbol === selected), [trades, selected]);
  const chartPositions = useMemo(() => positions.filter((p) => p.symbol === selected), [positions, selected]);
  const coinsByName = useMemo(() => signals.toSorted((a, b) => a.symbol.localeCompare(b.symbol)), [signals]);
  const sparks = useMemo(
    () => new Map(signals.map((s) => [s.symbol, recentCloses(history, s.symbol)] as const)),
    [signals, history],
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

      <Section
        id="posicoes"
        title="Suas posições"
        icon={<Wallet size={ICON} aria-hidden />}
        lead="Registre aqui o que você comprou. O painel acompanha cada compra e avisa quando for hora de vender."
      >
        <PositionsSection positions={positions} closed={closed} coins={coinsByName} onChanged={onChanged} />
      </Section>

      <Section
        id="moedas"
        title="Todas as moedas"
        icon={<Coins size={ICON} aria-hidden />}
        lead="Só Bitcoin e Ethereum recebem recomendação de compra. As outras são acompanhadas. Clique numa moeda para ver o gráfico e o histórico dela."
      >
        <MarketTable rows={signals} recommended={RECOMMENDED_SYMBOLS} sparks={sparks} selected={selected} onSelect={setSelected} />
      </Section>

      <section aria-labelledby="detalhe" className="mt-16">
        <h2 id="detalhe" className="flex items-center gap-3 text-lg font-semibold">
          <CoinLogo symbol={selected} size={28} />
          {coinFullName(selected)} ({coin}) desde {fmt.day(chartHistory[0]?.timestamp ?? null)}
          <ChartLineUp size={ICON} className="text-muted" aria-hidden />
        </h2>
        <div className="mt-5">
          <Block>
            <PriceChart history={chartHistory} trades={chartTrades} positions={chartPositions} />
          </Block>
          <h3 className="mt-8 font-medium">Cada período em que a regra mandou comprar ou segurar {coin}</h3>
          <div className="mt-3">
            <TradeList trades={chartTrades} coin={coin} recommended={RECOMMENDED_SYMBOLS.has(selected)} />
          </div>
        </div>
      </section>

      <Section id="funciona" title="A regra de compra funciona?" icon={<Scales size={ICON} aria-hidden />}>
        <BacktestPanel performance={performance} trades={trades} />
      </Section>

      <Section id="como" title="Como funciona" icon={<Info size={ICON} aria-hidden />}>
        <HowItWorks />
      </Section>
    </main>
  );
}
