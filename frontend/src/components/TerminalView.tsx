import { useEffect, useState } from "react";
import { loadSignals, undervalued } from "../data/loadSignals";
import type { DailySignal } from "../types/signals";

type State =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly rows: readonly DailySignal[]; readonly asOf: Date | null };

const price = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 6 });
const fixed = (n: number | null, digits: number): string => (n === null ? "—" : n.toFixed(digits));

export function TerminalView() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let alive = true;
    loadSignals()
      .then((all) => {
        if (alive) setState({ status: "ready", rows: undervalued(all), asOf: all[0]?.timestamp ?? null });
      })
      .catch((err: unknown) => {
        if (alive) setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <main className="min-h-screen bg-black p-4 font-mono text-sm text-green-400 sm:p-8">
      <h1 className="mb-1 text-white">&gt; daily_signals</h1>
      {state.status === "loading" && <p>carregando...</p>}
      {state.status === "error" && <p className="text-red-500">erro: {state.message}</p>}
      {state.status === "ready" && (
        <>
          <p className="mb-4 text-neutral-400">
            ciclo {state.asOf?.toISOString().slice(0, 10) ?? "—"} · {state.rows.length} ativo(s) subvalorizado(s)
          </p>
          {state.rows.length === 0 ? (
            <p className="text-neutral-400">nenhum ativo atende aos critérios hoje.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-right">
                <thead>
                  <tr className="border-b border-green-400 text-white">
                    <th className="py-1 pr-6 text-left font-normal">Ativo</th>
                    <th className="py-1 pr-6 font-normal">Preço</th>
                    <th className="py-1 pr-6 font-normal">Z-Score</th>
                    <th className="py-1 font-normal">F&amp;G</th>
                  </tr>
                </thead>
                <tbody>
                  {state.rows.map((s) => (
                    <tr key={s.symbol} className="border-b border-neutral-800">
                      <td className="py-1 pr-6 text-left text-white">{s.symbol}</td>
                      <td className="py-1 pr-6">{price.format(s.close)}</td>
                      <td className="py-1 pr-6 text-red-400">{fixed(s.zscore_90, 2)}</td>
                      <td className="py-1">{s.fng_value ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </main>
  );
}
