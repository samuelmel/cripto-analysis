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
  type Tone,
} from "../data/analytics";
import { coinFullName } from "../data/coins";
import type { DailySignal, Forecast } from "../types/signals";
import { CoinLabel } from "./CoinLabel";
import { Term } from "./Glossary";
import { STAGE_ICON } from "./icons";
import { DistanceBar } from "./Sections";
import { Sparkline } from "./Sparkline";
import { Badge, Block, TEXT_TONE } from "./ui";

/* ---------- faixa de estado ---------- */

export interface StripFacts {
  readonly marketText: string;
  readonly marketTone: Tone;
  readonly marketNote: "up" | "down" | "none";
  readonly collectedAt: string;
  readonly freshness: string;
  readonly freshnessTone: Tone;
  readonly analysisDay: string;
}

function Fact({ label, value, note, tone = "neutral" }: {
  readonly label: string;
  readonly value: string;
  readonly note: React.ReactNode;
  readonly tone?: Tone;
}) {
  return (
    <div className="md:px-6 md:first:pl-0 md:last:pr-0">
      <p className="text-[13px] text-muted">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${TEXT_TONE[tone]}`}>{value}</p>
      <p className="mt-0.5 text-[13px] text-muted">{note}</p>
    </div>
  );
}

export function StatusStrip({ facts }: { readonly facts: StripFacts }) {
  return (
    <Block>
      <div className="grid gap-5 md:grid-cols-3 md:gap-0 md:divide-x md:divide-hairline">
        <Fact
          label="Estado do mercado"
          value={facts.marketText}
          tone={facts.marketTone}
          note={
            facts.marketNote === "none" ? (
              "Sem dados confiáveis do Bitcoin."
            ) : (
              <>
                Bitcoin {facts.marketNote === "up" ? "acima" : "abaixo"} da <Term id="sma200">média de 200 dias</Term>
              </>
            )
          }
        />
        <Fact label="Atualização dos dados" value={facts.collectedAt} tone="neutral" note={<span className={TEXT_TONE[facts.freshnessTone]}>{facts.freshness}</span>} />
        <Fact label="Data da análise" value={facts.analysisDay} note="Último fechamento diário, em UTC" />
      </div>
    </Block>
  );
}

/* ---------- avisos ---------- */

const NOTICE_ICON = { panic: Warning, stale: ClockCountdown, collect: WifiSlash } as const;
const NOTICE_BG: Record<"warning" | "critical", string> = { warning: "bg-warning-bg", critical: "bg-critical-bg" };

/** Área de avisos, visualmente separada das recomendações. Sem avisos, vira uma linha tranquila. */
export function NoticesArea({ items }: { readonly items: readonly Notice[] }) {
  if (items.length === 0) {
    return (
      <p className="flex items-center gap-2 text-muted">
        <CheckCircle size={20} className="text-good" aria-hidden />
        Nenhum aviso hoje: dados em dia, nenhuma falha de coleta e nenhuma moeda em pânico.
      </p>
    );
  }
  return (
    <section aria-label="Avisos" className="rounded-md border border-hairline bg-ground p-4">
      <h2 className="text-[15px] font-semibold">Avisos de hoje</h2>
      <p className="mt-0.5 text-[13px] text-muted">Avisos não são recomendações de compra nem de venda.</p>
      <ul className="mt-3 grid gap-3 md:grid-cols-2">
        {items.map((n) => {
          const Icon = NOTICE_ICON[n.kind];
          const critical = n.tone === "critical";
          return (
            <li key={`${n.kind}:${n.title}`} className={`flex gap-3 rounded-md p-3 ${NOTICE_BG[critical ? "critical" : "warning"]}`}>
              <Icon size={22} className={`mt-0.5 shrink-0 ${critical ? "text-critical" : "text-warning"}`} aria-hidden />
              <div>
                <p className={`font-medium ${critical ? "text-critical" : "text-warning"}`}>{n.title}</p>
                <p className="mt-0.5 text-[14px]">{n.text}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ---------- cartão de moeda ---------- */

export function CoinCard({ signal, view, change1, change30, closes, selected, onSelect }: {
  readonly signal: DailySignal;
  readonly view: SignalView;
  readonly change1: number | null;
  readonly change30: number | null;
  readonly closes: readonly number[];
  readonly selected: boolean;
  readonly onSelect: (symbol: string) => void;
}) {
  const Icon = STAGE_ICON[view.stage];
  const distance = distanceFromAverage(signal.close, signal.sma_200);
  return (
    <article aria-label={coinFullName(signal.symbol)} className={`rounded-md border bg-surface p-6 ${selected ? "border-signal" : "border-hairline"}`}>
      <div className="flex items-start justify-between gap-3">
        <CoinLabel symbol={signal.symbol} detailed size={36} />
        <Badge tone={view.tone}>
          <span className="flex items-center gap-1.5">
            {Icon !== null && <Icon size={14} aria-hidden />}
            {view.text}
          </span>
        </Badge>
      </div>
      <p className="mt-4 text-[32px] font-medium leading-tight">{fmt.price(signal.close)}</p>
      <p className="mt-1 text-[13px] text-muted">Fechamento diário de {fmt.day(signal.timestamp)}</p>
      <dl className="mt-4 grid grid-cols-2 gap-4">
        <div>
          <dt className="text-[13px] text-muted">Em 24 horas</dt>
          <dd className={`num font-medium ${TEXT_TONE[signTone(change1)]}`}>{fmt.pct(change1)}</dd>
        </div>
        <div>
          <dt className="text-[13px] text-muted">Em 30 dias</dt>
          <dd className={`num font-medium ${TEXT_TONE[signTone(change30)]}`}>{fmt.pct(change30)}</dd>
        </div>
      </dl>
      <div className="mt-4 border-t border-hairline pt-3">
        <p className="text-[13px] text-muted">
          Distância da <Term id="sma200">média de 200 dias</Term>
        </p>
        <div className="mt-1 flex items-center justify-between gap-3">
          <DistanceBar pct={distance} />
          <Sparkline values={closes} label={`Preço de ${coinName(signal.symbol)}`} />
        </div>
      </div>
      <p className="mt-3 text-[14px]">{view.why}</p>
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => onSelect(signal.symbol)}
        className="mt-4 rounded-sm border border-hairline px-3 py-1.5 text-[14px] font-medium transition-colors hover:bg-ground aria-pressed:border-signal aria-pressed:bg-signal-bg"
      >
        {selected ? "Mostrado no gráfico" : "Mostrar no gráfico"}
      </button>
    </article>
  );
}

/* ---------- previsão ---------- */

function BandRow({ f, limit }: { readonly f: Forecast; readonly limit: number }) {
  const left = bandPercent(f.p10_pct, limit);
  const right = bandPercent(f.p90_pct, limit);
  return (
    <li className="grid grid-cols-[5.5rem_1fr] items-center gap-3 sm:grid-cols-[6.5rem_1fr_auto]">
      <span className="font-medium">{horizonName(f.horizon_days)}</span>
      <span aria-hidden className="relative block h-3 rounded-sm bg-ground sm:order-none">
        <span className="absolute inset-y-0 left-1/2 w-px bg-muted" />
        <span
          className="absolute inset-y-0 rounded-sm border border-dashed border-series-price bg-series-price/15"
          style={{ left: `${left}%`, width: `${Math.max(right - left, 1)}%` }}
        />
        <span className="absolute -top-0.5 h-4 w-0.5 bg-ink" style={{ left: `${bandPercent(f.p50_pct, limit)}%` }} />
      </span>
      <span className="num col-span-2 text-[14px] sm:col-span-1 sm:text-right">
        {fmt.pct(f.p10_pct, 0)} a {fmt.pct(f.p90_pct, 0)}
        <span className="text-muted">, meio {fmt.pct(f.p50_pct, 1)}</span>
      </span>
    </li>
  );
}

/** Previsão de 1, 7 e 30 dias de cada moeda, sempre rotulada como estimativa. */
export function ForecastBlock({ forecast, symbols }: { readonly forecast: readonly Forecast[]; readonly symbols: readonly string[] }) {
  return (
    <Block>
      <h2 className="text-lg font-semibold">Previsão de preço (estimativa)</h2>
      <p className="mt-1 max-w-[68ch] text-muted">
        A <Term id="faixa">faixa de previsão</Term> vai de P10 a P90: onde o retorno deve ficar em 8 de cada 10 vezes. É uma estimativa estatística, não uma garantia.
      </p>
      <div className="mt-5 grid gap-8 md:grid-cols-2">
        {symbols.map((symbol) => {
          const rows = modelForecast(forecast, symbol);
          const limit = Math.max(1, ...rows.flatMap((r) => [Math.abs(r.p10_pct), Math.abs(r.p90_pct)]));
          const noEdge = rows.length > 0 && rows.every((r) => !r.beats_baseline);
          return (
            <section key={symbol} aria-label={`Previsão de ${coinFullName(symbol)}`} className="border-t border-hairline pt-4">
              <p className="font-medium">{coinFullName(symbol)}</p>
              {rows.length === 0 ? (
                <p className="mt-3 text-muted">Sem previsão para esta moeda hoje (dados insuficientes ou desatualizados).</p>
              ) : (
                <>
                  <ul className="mt-3 space-y-3">
                    {rows.map((r) => <BandRow key={r.horizon_days} f={r} limit={limit} />)}
                  </ul>
                  {noEdge && (
                    <p className="mt-4">
                      <Badge tone="warning">Sem vantagem demonstrada sobre o preço de hoje</Badge>
                    </p>
                  )}
                  {!noEdge && rows.some((r) => !r.beats_baseline) && (
                    <p className="mt-4 text-[13px] text-warning">
                      Sem vantagem demonstrada em {rows.filter((r) => !r.beats_baseline).map((r) => `${r.horizon_days} d`).join(", ")}.
                    </p>
                  )}
                  <p className="mt-2 text-[13px] text-muted">
                    Mesmo sem vantagem, a faixa serve como medida de incerteza. Traço escuro: valor do meio (P50).
                  </p>
                </>
              )}
            </section>
          );
        })}
      </div>
    </Block>
  );
}
