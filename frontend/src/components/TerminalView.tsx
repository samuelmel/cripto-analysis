import { useEffect, useMemo, useState } from "react";
import { allByZscore, byStage, byStrategy, fmt, historyOf, withAlert } from "../data/analytics";
import { MissingFileError, loadDashboard } from "../data/loadSignals";
import type { Dashboard } from "../types/signals";
import { PriceChart } from "./PriceChart";
import { BacktestPanel, PositionsTable, Section, SignalTable, TradeList } from "./Sections";

type State =
  | { readonly status: "loading" }
  | { readonly status: "missing" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly data: Dashboard };

export function TerminalView() {
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
    <main className="min-h-screen bg-black p-4 font-mono text-sm text-green-400 sm:p-8">
      <h1 className="mb-1 text-white">&gt; crypto-analyzer</h1>
      {state.status === "loading" && <p>carregando...</p>}
      {state.status === "missing" && (
        <p className="text-yellow-400">
          sem dados ainda. rode o pipeline: <span className="text-white">uv run python -m src.pipeline</span>
        </p>
      )}
      {state.status === "error" && <p className="text-red-500">erro: {state.message}</p>}
      {state.status === "ready" && <Ready data={state.data} />}
    </main>
  );
}

function Ready({ data }: { readonly data: Dashboard }) {
  const { signals, history, trades, positions } = data;
  const first = signals[0];
  const fresh = withAlert(signals, "COMPRAR AGORA");
  const toSell = positions.filter((p) => p.action === "VENDER");
  const [selected, setSelected] = useState<string>(positions[0]?.symbol ?? first?.symbol ?? "BTC/USDT");

  const signalTrades = useMemo(() => byStrategy(trades, "SINAL"), [trades]);
  const chartHistory = useMemo(() => historyOf(history, selected), [history, selected]);
  const chartTrades = useMemo(() => signalTrades.filter((t) => t.symbol === selected), [signalTrades, selected]);
  const chartPositions = useMemo(() => positions.filter((p) => p.symbol === selected), [positions, selected]);
  const symbols = useMemo(() => [...new Set(history.map((h) => h.symbol))].toSorted(), [history]);
  const since = chartHistory[0]?.timestamp ?? null;

  return (
    <>
      <p className="mb-6 text-neutral-400">
        ciclo {fmt.day(first?.timestamp ?? null)} · {signals.length} ativos · F&amp;G {first?.fng_value ?? "—"}{" "}
        {first?.fng_classification ?? ""} · base desde {fmt.day(history.reduce<Date | null>((m, h) => (m === null || h.timestamp < m ? h.timestamp : m), null))}
      </p>

      {toSell.length > 0 && (
        <p className="mb-3 bg-red-600 px-2 py-1 text-white">
          ! vender: {toSell.map((p) => `${p.symbol} (${p.reason ?? ""})`).join(", ")}
        </p>
      )}
      {fresh.length > 0 && (
        <p className="mb-3 bg-red-600 px-2 py-1 text-white">! disparou hoje: {fresh.map((s) => s.symbol).join(", ")}</p>
      )}

      <Section title="minhas posições" hint="VENDER quando bater STOP (-20%), PROTEGER LUCRO (subiu 15% e recuou 10% do pico), ALVO (voltou à média de 90d), SOBRECOMPRADO (RSI ≥ 70) ou TEMPO (180d)">
        <PositionsTable positions={positions} />
      </Section>

      <Section title="comprar" hint="z-score < -2.5, RSI < 30 e F&G em pânico (< 25)">
        <SignalTable rows={byStage(signals, "COMPRAR")} onSelect={setSelected} />
      </Section>

      <Section title="preparar (radar)" hint="z-score < -1.5 e RSI < 40 — escorregando para a zona de compra">
        <SignalTable rows={byStage(signals, "PREPARAR")} onSelect={setSelected} />
      </Section>

      <Section title="todos os ativos" hint="clique para ver o gráfico · ordenado do mais esticado para baixo ao mais esticado para cima">
        <SignalTable rows={allByZscore(signals)} onSelect={setSelected} />
      </Section>

      <Section title={`gráfico ${selected}`} hint={`desde ${fmt.day(since)} · verde: preço · cinza: SMA 90 · ▲C: sinal COMPRAR · ▼: saída simulada · ●: sua compra`}>
        <div className="mb-3 flex flex-wrap gap-2">
          {symbols.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSelected(s)}
              className={`border px-2 ${s === selected ? "border-green-400 text-white" : "border-neutral-800 text-neutral-500 hover:text-white"}`}
            >
              {s.replace("/USDT", "")}
            </button>
          ))}
        </div>
        <PriceChart history={chartHistory} trades={chartTrades} positions={chartPositions} />
        <p className="mt-4 mb-2 text-white">sinais COMPRAR de {selected} no histórico</p>
        <TradeList trades={chartTrades} />
      </Section>

      <Section title="backtest" hint="cada sinal COMPRAR desde 2017 simulado com as mesmas regras de venda das suas posições, comparado a comprar 1×/semana sem critério">
        <BacktestPanel signal={signalTrades} reference={byStrategy(trades, "REFERENCIA")} />
      </Section>
    </>
  );
}
