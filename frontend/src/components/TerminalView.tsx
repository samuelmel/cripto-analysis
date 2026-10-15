import { useEffect, useState } from "react";
import { SignalsMissingError, byStage, loadSignals, withAlert } from "../data/loadSignals";
import type { DailySignal } from "../types/signals";

type State =
  | { readonly status: "loading" }
  | { readonly status: "missing" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly signals: readonly DailySignal[] };

const price = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 6 });
const fixed = (n: number | null, digits: number): string => (n === null ? "—" : n.toFixed(digits));

function SignalTable({ rows }: { readonly rows: readonly DailySignal[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-right">
        <thead>
          <tr className="border-b border-green-400 text-white">
            <th className="py-1 pr-6 text-left font-normal">Ativo</th>
            <th className="py-1 pr-6 font-normal">Preço</th>
            <th className="py-1 pr-6 font-normal">Z-Score</th>
            <th className="py-1 pr-6 font-normal">RSI</th>
            <th className="py-1 font-normal">F&amp;G</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.symbol} className="border-b border-neutral-800">
              <td className="py-1 pr-6 text-left text-white">
                {s.symbol}
                {s.alert === "COMPRAR AGORA" && <span className="ml-2 bg-red-600 px-1 text-white">NOVO</span>}
              </td>
              <td className="py-1 pr-6">{price.format(s.close)}</td>
              <td className="py-1 pr-6 text-red-400">{fixed(s.zscore_90, 2)}</td>
              <td className="py-1 pr-6">{fixed(s.rsi_14, 1)}</td>
              <td className="py-1">{s.fng_value ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({ title, hint, rows }: { readonly title: string; readonly hint: string; readonly rows: readonly DailySignal[] }) {
  return (
    <section className="mb-8">
      <h2 className="text-white">
        {title} <span className="text-neutral-500">({rows.length})</span>
      </h2>
      <p className="mb-2 text-neutral-500">{hint}</p>
      {rows.length === 0 ? <p className="text-neutral-600">nenhum ativo.</p> : <SignalTable rows={rows} />}
    </section>
  );
}

export function TerminalView() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let alive = true;
    loadSignals()
      .then((signals) => {
        if (alive) setState({ status: "ready", signals });
      })
      .catch((err: unknown) => {
        if (!alive) return;
        if (err instanceof SignalsMissingError) setState({ status: "missing" });
        else setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <main className="min-h-screen bg-black p-4 font-mono text-sm text-green-400 sm:p-8">
      <h1 className="mb-1 text-white">&gt; daily_signals</h1>
      {state.status === "loading" && <p>carregando...</p>}
      {state.status === "missing" && (
        <p className="text-yellow-400">
          sem dados ainda. rode o pipeline: <span className="text-white">uv run python -m src.pipeline</span>
        </p>
      )}
      {state.status === "error" && <p className="text-red-500">erro: {state.message}</p>}
      {state.status === "ready" && <Ready signals={state.signals} />}
    </main>
  );
}

function Ready({ signals }: { readonly signals: readonly DailySignal[] }) {
  const first = signals[0];
  const fresh = withAlert(signals, "COMPRAR AGORA");
  const exits = withAlert(signals, "SAIU DO RADAR");
  return (
    <>
      <p className="mb-6 text-neutral-400">
        ciclo {first?.timestamp.toISOString().slice(0, 10) ?? "—"} · {signals.length} ativos · F&amp;G{" "}
        {first?.fng_value ?? "—"} {first?.fng_classification ?? ""}
      </p>
      {fresh.length > 0 && (
        <p className="mb-6 bg-red-600 px-2 py-1 text-white">
          ! disparou hoje: {fresh.map((s) => s.symbol).join(", ")}
        </p>
      )}
      <Section
        title="COMPRAR"
        hint="z-score < -2.5, RSI < 30 e F&G em pânico (< 25)"
        rows={byStage(signals, "COMPRAR")}
      />
      <Section
        title="PREPARAR"
        hint="radar: z-score < -1.5 e RSI < 40 — escorregando para a zona de compra"
        rows={byStage(signals, "PREPARAR")}
      />
      {exits.length > 0 && (
        <p className="text-neutral-500">saíram do radar hoje: {exits.map((s) => s.symbol).join(", ")}</p>
      )}
    </>
  );
}
