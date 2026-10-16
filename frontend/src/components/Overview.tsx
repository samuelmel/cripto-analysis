import { CheckCircle, ClockCountdown, Warning, WifiSlash } from "@phosphor-icons/react";
import {
  bandPercent,
  coinName,
  distanceFromAverage,
  fmt,
  horizonName,
  modelForecast,
  signTone,
  type Notice,
  type SignalView,
} from "../data/analytics";
import { coinFullName } from "../data/coins";
import type { DailySignal, Forecast } from "../types/signals";
import { CoinLabel } from "./CoinLabel";
import { Term } from "./Glossary";
import { STAGE_ICON } from "./icons";
import { DistanceBar } from "./Sections";
import { Sparkline } from "./Sparkline";
import { Badge, Empty, Table, TEXT_TONE, cell, numCell } from "./ui";

/* ---------- avisos ---------- */

const NOTICE_ICON = { panic: Warning, stale: ClockCountdown, collect: WifiSlash } as const;

/** Avisos do dia numa faixa fina, separada das recomendações. Sem avisos, uma linha tranquila de uma só linha. */
export function NoticesBar({ items }: { readonly items: readonly Notice[] }) {
  if (items.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-[12px] text-muted">
        <CheckCircle size={16} className="text-good" aria-hidden />
        Nenhum aviso: dados em dia, nenhuma falha de coleta e nenhuma moeda em pânico.
      </p>
    );
  }
  return (
    <section aria-label="Avisos (não são recomendações de compra nem de venda)" className="rounded-md border border-hairline bg-surface px-3 py-1.5">
      <ul className="grid gap-x-6 gap-y-0.5 md:grid-cols-2">
        {items.map((n) => {
          const Icon = NOTICE_ICON[n.kind];
          const critical = n.tone === "critical";
          return (
            <li key={`${n.kind}:${n.title}`} className="flex min-w-0 items-start gap-2 text-[12px]" title={`${n.title}. ${n.text}`}>
              <Icon size={16} className={`mt-px shrink-0 ${critical ? "text-critical" : "text-warning"}`} aria-hidden />
              <span className="min-w-0">
                <span className={`font-medium ${critical ? "text-critical" : "text-warning"}`}>{n.title}.</span>{" "}
                <span className="text-muted">{n.text}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ---------- regra principal: BTC e ETH ---------- */

/** BTC e ETH na regra da média de 200 dias: sinal, preço, variação, distância da média e mini-gráfico, alinhados. */
export function CoreTable({ rows, selected, onSelect }: {
  readonly rows: readonly {
    readonly signal: DailySignal;
    readonly view: SignalView;
    readonly change1: number | null;
    readonly change30: number | null;
    readonly closes: readonly number[];
  }[];
  readonly selected: string;
  readonly onSelect: (symbol: string) => void;
}) {
  if (rows.length === 0) return <Empty title="Sem dados de BTC e ETH">Rode o pipeline para publicar os sinais.</Empty>;
  return (
    <Table
      flush
      caption="Regra principal da média de 200 dias para Bitcoin e Ethereum"
      columns={[
        { label: "Moeda" }, { label: "Sinal" }, { label: "Preço", numeric: true }, { label: "24 h", numeric: true },
        { label: "30 d", numeric: true, narrow: "hide" }, { label: "Dist. média 200", numeric: true, narrow: "hide" }, { label: "90 d", narrow: "hide" },
      ]}
    >
      {rows.map(({ signal, view, change1, change30, closes }) => {
        const Icon = STAGE_ICON[view.stage];
        const isSelected = signal.symbol === selected;
        return (
          <tr
            key={signal.symbol}
            tabIndex={0}
            aria-selected={isSelected}
            onClick={() => onSelect(signal.symbol)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(signal.symbol);
              }
            }}
            title={view.why}
            className={`cursor-pointer border-b border-hairline hover:bg-ground ${isSelected ? "bg-signal-bg" : ""}`}
          >
            <td className={cell}><CoinLabel symbol={signal.symbol} size={20} /></td>
            <td className={cell}>
              <Badge tone={view.tone}>
                <span className="flex items-center gap-1">
                  {Icon !== null && <Icon size={12} aria-hidden />}
                  {view.text}
                </span>
              </Badge>
            </td>
            <td className={numCell}>{fmt.price(signal.close)}</td>
            <td className={`${numCell} ${TEXT_TONE[signTone(change1)]}`}>{fmt.pct(change1)}</td>
            <td className={`${numCell} hidden md:table-cell ${TEXT_TONE[signTone(change30)]}`}>{fmt.pct(change30)}</td>
            <td className={`${numCell} hidden md:table-cell`}><DistanceBar pct={distanceFromAverage(signal.close, signal.sma_200)} /></td>
            <td className={`${cell} hidden md:table-cell`}><Sparkline values={closes} label={`Preço de ${coinName(signal.symbol)}`} /></td>
          </tr>
        );
      })}
    </Table>
  );
}

/* ---------- previsão ---------- */

function BandRow({ f, limit }: { readonly f: Forecast; readonly limit: number }) {
  const left = bandPercent(f.p10_pct, limit);
  const right = bandPercent(f.p90_pct, limit);
  return (
    <li className="grid grid-cols-[5rem_1fr_auto] items-center gap-2 text-[12px]">
      <span className="font-medium">{horizonName(f.horizon_days)}</span>
      <span aria-hidden className="relative block h-2 rounded-sm bg-ground">
        <span className="absolute inset-y-0 left-1/2 w-px bg-muted" />
        <span
          className="absolute inset-y-0 rounded-sm border border-dashed border-series-price bg-series-price/15"
          style={{ left: `${left}%`, width: `${Math.max(right - left, 1)}%` }}
        />
        <span className="absolute -top-0.5 h-3 w-0.5 bg-ink" style={{ left: `${bandPercent(f.p50_pct, limit)}%` }} />
      </span>
      <span className="num text-right">
        {fmt.pct(f.p10_pct, 0)} a {fmt.pct(f.p90_pct, 0)}
      </span>
    </li>
  );
}

/** Previsão de 1, 7 e 30 dias de cada moeda, lado a lado e sempre rotulada como estimativa. */
export function ForecastMini({ forecast, symbols }: { readonly forecast: readonly Forecast[]; readonly symbols: readonly string[] }) {
  return (
    <div>
      <p className="text-[12px] text-muted">
        <Term id="faixa">Faixa P10 a P90</Term>: onde o retorno deve ficar em 8 de cada 10 vezes. Estimativa estatística, não garantia; traço escuro = valor do meio.
      </p>
      <div className="mt-2 grid gap-x-6 gap-y-3 md:grid-cols-2">
        {symbols.map((symbol) => {
          const rows = modelForecast(forecast, symbol);
          const limit = Math.max(1, ...rows.flatMap((r) => [Math.abs(r.p10_pct), Math.abs(r.p90_pct)]));
          const noEdge = rows.length > 0 && rows.every((r) => !r.beats_baseline);
          return (
            <section key={symbol} aria-label={`Previsão de ${coinFullName(symbol)}`}>
              <p className="flex items-center justify-between gap-2 text-[13px] font-medium">
                {coinFullName(symbol)}
                {noEdge && <Badge tone="warning">Sem vantagem demonstrada</Badge>}
              </p>
              {rows.length === 0 ? (
                <p className="mt-1 text-[12px] text-muted">Sem previsão hoje (dados insuficientes ou desatualizados).</p>
              ) : (
                <ul className="mt-1.5 space-y-1.5">{rows.map((r) => <BandRow key={r.horizon_days} f={r} limit={limit} />)}</ul>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
