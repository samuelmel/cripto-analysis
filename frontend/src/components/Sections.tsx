import type { ReactNode } from "react";
import { byReason, fmt, signalHasEdge, summarize, type TradeSummary } from "../data/analytics";
import { EXIT_REASONS, type DailySignal, type Position, type Stage, type Trade } from "../types/signals";

const th = "py-1 pr-4 font-normal text-right first:text-left";
const td = "py-1 pr-4 text-right first:text-left";
const tone = (n: number | null): string => (n === null ? "" : n > 0 ? "text-green-400" : n < 0 ? "text-red-400" : "");
const STAGE_TONE: Record<Stage, string> = { COMPRAR: "text-red-400", PREPARAR: "text-yellow-400", NEUTRO: "text-neutral-500" };

export function Section({ title, hint, children }: { readonly title: string; readonly hint?: string; readonly children: ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="text-white">&gt; {title}</h2>
      {hint !== undefined && <p className="mb-2 text-neutral-500">{hint}</p>}
      {children}
    </section>
  );
}

function Table({ head, children }: { readonly head: readonly string[]; readonly children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse whitespace-nowrap">
        <thead>
          <tr className="border-b border-green-400 text-white">
            {head.map((h, i) => <th key={`${i}:${h}`} className={th}>{h}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function PositionsTable({ positions }: { readonly positions: readonly Position[] }) {
  if (positions.length === 0) {
    return (
      <p className="text-neutral-500">
        nenhuma posição. registre uma compra:{" "}
        <span className="text-white">uv run python -m src.positions add BTC/USDT 83000 0.01</span>
      </p>
    );
  }
  return (
    <Table head={["Ativo", "Entrada", "Atual", "Resultado", "P&L", "Ação", "Motivo", "Stop", "Trava lucro", "Alvo (SMA90)"]}>
      {positions.map((p) => (
        <tr key={p.position_id} className="border-b border-neutral-800">
          <td className={`${td} text-white`}>{p.symbol} <span className="text-neutral-600">{p.position_id}</span></td>
          <td className={td}>{fmt.price(p.entry_price)} <span className="text-neutral-600">{fmt.day(p.entry_ts)}</span></td>
          <td className={td}>{fmt.price(p.last_close)}</td>
          <td className={`${td} ${tone(p.return_pct)}`}>{fmt.pct(p.return_pct)}</td>
          <td className={`${td} ${tone(p.pnl_usd)}`}>{fmt.usd(p.pnl_usd)}</td>
          <td className={td}>
            <span className={p.action === "VENDER" ? "bg-red-600 px-1 text-white" : "bg-green-700 px-1 text-white"}>{p.action}</span>
          </td>
          <td className={td}>{p.reason === null ? "—" : `${p.reason} desde ${fmt.day(p.signal_ts)}`}</td>
          <td className={td}>{fmt.price(p.stop_price)}</td>
          <td className={td}>{fmt.price(p.trail_price)}</td>
          <td className={td}>{fmt.price(p.target_price)}</td>
        </tr>
      ))}
    </Table>
  );
}

export function SignalTable({ rows, onSelect }: { readonly rows: readonly DailySignal[]; readonly onSelect: (symbol: string) => void }) {
  if (rows.length === 0) return <p className="text-neutral-600">nenhum ativo.</p>;
  return (
    <Table head={["Ativo", "Preço", "Z-Score", "RSI", "F&G", "Estágio", "Alerta"]}>
      {rows.map((s) => (
        <tr key={s.symbol} className="cursor-pointer border-b border-neutral-800 hover:bg-neutral-900" onClick={() => onSelect(s.symbol)}>
          <td className={`${td} text-white underline decoration-neutral-700`}>{s.symbol}</td>
          <td className={td}>{fmt.price(s.close)}</td>
          <td className={`${td} ${tone(s.zscore_90)}`}>{fmt.num(s.zscore_90)}</td>
          <td className={td}>{fmt.num(s.rsi_14, 1)}</td>
          <td className={td}>{s.fng_value ?? "—"}</td>
          <td className={`${td} ${STAGE_TONE[s.stage]}`}>{s.stage}</td>
          <td className={td}>{s.alert === "COMPRAR AGORA" ? <span className="bg-red-600 px-1 text-white">{s.alert}</span> : s.alert ?? ""}</td>
        </tr>
      ))}
    </Table>
  );
}

function SummaryRow({ label, s }: { readonly label: string; readonly s: TradeSummary }) {
  return (
    <tr className="border-b border-neutral-800">
      <td className={`${td} text-white`}>{label}</td>
      <td className={td}>{s.count}</td>
      <td className={td}>{fmt.num(s.winRate, 0)}%</td>
      <td className={`${td} ${tone(s.mean)}`}>{fmt.pct(s.mean)}</td>
      <td className={`${td} ${tone(s.median)}`}>{fmt.pct(s.median)}</td>
      <td className={`${td} text-red-400`}>{fmt.pct(s.worst)}</td>
      <td className={`${td} text-green-400`}>{fmt.pct(s.best)}</td>
      <td className={td}>{fmt.num(s.meanDays, 0)}</td>
    </tr>
  );
}

const SUMMARY_HEAD = ["", "Operações", "Acerto", "Média", "Mediana", "Pior", "Melhor", "Dias"] as const;

export function BacktestPanel({ signal, reference }: { readonly signal: readonly Trade[]; readonly reference: readonly Trade[] }) {
  const s = summarize(signal);
  const r = summarize(reference);
  const edge = signalHasEdge(s, r);
  const reasons = byReason(signal);
  return (
    <>
      {edge === false && (
        <p className="mb-3 border border-red-600 px-2 py-1 text-red-400">
          atenção: historicamente o sinal COMPRAR rendeu menos que comprar num dia qualquer com as mesmas regras de
          venda. ele não tem vantagem comprovada — use como alerta de pânico, não como ordem de compra.
        </p>
      )}
      {edge === true && (
        <p className="mb-3 border border-green-600 px-2 py-1 text-green-400">
          o sinal COMPRAR superou a referência no histórico.
        </p>
      )}
      <Table head={SUMMARY_HEAD}>
        <SummaryRow label="sinal COMPRAR" s={s} />
        <SummaryRow label="referência (1×/semana)" s={r} />
      </Table>
      <p className="mt-6 mb-2 text-white">saídas do sinal COMPRAR por motivo</p>
      <Table head={SUMMARY_HEAD}>
        {EXIT_REASONS.flatMap((reason) => {
          const summary = reasons.get(reason);
          return summary === undefined ? [] : [<SummaryRow key={reason} label={reason} s={summary} />];
        })}
      </Table>
    </>
  );
}

export function TradeList({ trades }: { readonly trades: readonly Trade[] }) {
  if (trades.length === 0) return <p className="text-neutral-600">nenhum sinal COMPRAR no histórico deste ativo.</p>;
  return (
    <Table head={["Entrada", "Preço", "Saída", "Preço", "Motivo", "Resultado", "Dias"]}>
      {trades.toSorted((a, b) => b.entry_ts.getTime() - a.entry_ts.getTime()).map((t) => (
        <tr key={t.trade_id} className="border-b border-neutral-800">
          <td className={`${td} text-white`}>{fmt.day(t.entry_ts)}</td>
          <td className={td}>{fmt.price(t.entry_price)}</td>
          <td className={td}>{t.status === "ABERTA" ? "aberta" : fmt.day(t.exit_ts)}</td>
          <td className={td}>{fmt.price(t.exit_price)}</td>
          <td className={td}>{t.exit_reason ?? "—"}</td>
          <td className={`${td} ${tone(t.return_pct)}`}>{fmt.pct(t.return_pct)}</td>
          <td className={td}>{t.days_held ?? "—"}</td>
        </tr>
      ))}
    </Table>
  );
}
