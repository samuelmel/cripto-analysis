import {
  ColorType,
  CrosshairMode,
  PriceScaleMode,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { fmt } from "../data/analytics";
import type { Forecast, HistoryPoint, Position, Trade } from "../types/signals";
import { Term } from "./Glossary";
import { Collapsible } from "./ui";

/* Cores do DESIGN.md (validadas com validate_palette.js). O canvas não lê CSS vars.
   A estimativa usa a cor do preço com transparência e traço, para nunca se confundir com o histórico. */
const C = {
  surface: "#fcfcfb",
  muted: "#55544f",
  grid: "#ecebe6",
  axis: "#e1e0d9",
  price: "#2a78d6",
  average: "#eb6834",
  trend: "#4a3aa7",
  estimate: "rgba(42, 120, 214, 0.5)",
  estimateMid: "rgba(42, 120, 214, 0.9)",
  good: "#0ca30c",
  critical: "#d03b3b",
  ink: "#121417",
} as const;

const DAY_S = 86_400;
const TIP_WIDTH = 248;
const SOURCE_PRICE = "Binance, candle diário (UTC)";

const toTime = (d: Date): UTCTimestamp => Math.floor(d.getTime() / 1000) as UTCTimestamp;

interface Tip {
  readonly x: number;
  readonly title: string;
  readonly lines: readonly string[];
  readonly source: string;
  readonly estimate: boolean;
}

interface Props {
  readonly history: readonly HistoryPoint[];
  readonly trades: readonly Trade[];
  readonly positions: readonly Position[];
  /** Linhas do modelo para esta moeda (vazio = sem previsão). */
  readonly forecast: readonly Forecast[];
  readonly showForecast: boolean;
  /** Altura da área do gráfico em px (padrão 300): controlada pelo painel que o contém. */
  readonly height?: number;
}

/** Preço e médias de 90 e 200 dias, entradas e saídas da regra, suas compras e, se pedido, a faixa de previsão. */
export function PriceChart({ history, trades, positions, forecast, showForecast, height = 300 }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const withForecast = showForecast && forecast.length > 0;

  useEffect(() => {
    const el = container.current;
    if (el === null) return;
    const byTime = new Map(history.map((h) => [toTime(h.timestamp), h]));
    const last = history.at(-1);
    const estimates = new Map<UTCTimestamp, Forecast>();
    if (withForecast && last !== undefined) {
      for (const f of forecast) estimates.set((toTime(last.timestamp) + f.horizon_days * DAY_S) as UTCTimestamp, f);
    }

    const chart: IChartApi = createChart(el, {
      height,
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: C.surface },
        textColor: C.muted,
        fontFamily: '"IBM Plex Sans", system-ui, sans-serif',
        fontSize: 12,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: C.axis, mode: PriceScaleMode.Logarithmic, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: C.axis },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: { color: C.muted, style: LineStyle.Solid, width: 1, labelBackgroundColor: C.ink },
        horzLine: { color: C.muted, style: LineStyle.Solid, width: 1, labelBackgroundColor: C.ink },
      },
      localization: { locale: "pt-BR" },
    });

    const price = chart.addSeries(LineSeries, { color: C.price, lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    price.setData(history.map((h) => ({ time: toTime(h.timestamp), value: h.close })));

    const average = chart.addSeries(LineSeries, {
      color: C.average, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    average.setData(history.flatMap((h) => (h.sma_90 === null ? [] : [{ time: toTime(h.timestamp), value: h.sma_90 }])));

    const trend = chart.addSeries(LineSeries, {
      color: C.trend, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    trend.setData(history.flatMap((h) => (h.sma_200 === null ? [] : [{ time: toTime(h.timestamp), value: h.sma_200 }])));

    if (last !== undefined && estimates.size > 0) {
      const start = { time: toTime(last.timestamp), value: last.close };
      const bands = [
        { key: "p90_price", title: "P90 (estimativa)", color: C.estimate, width: 1 },
        { key: "p50_price", title: "P50 (estimativa)", color: C.estimateMid, width: 2 },
        { key: "p10_price", title: "P10 (estimativa)", color: C.estimate, width: 1 },
      ] as const;
      for (const band of bands) {
        const series = chart.addSeries(LineSeries, {
          color: band.color, lineWidth: band.width, lineStyle: LineStyle.Dashed, priceLineVisible: false,
          lastValueVisible: true, title: band.title, crosshairMarkerVisible: false,
        });
        series.setData([start, ...[...estimates].map(([time, f]) => ({ time, value: f[band.key] }))]);
      }
    }

    const markers: SeriesMarker<UTCTimestamp>[] = [
      ...trades.flatMap((t): SeriesMarker<UTCTimestamp>[] => [
        { time: toTime(t.entry_ts), position: "belowBar", color: C.price, shape: "arrowUp", size: 1 },
        ...(t.exit_ts === null
          ? []
          : [{
              time: toTime(t.exit_ts),
              position: "aboveBar" as const,
              color: (t.return_pct ?? 0) > 0 ? C.good : C.critical,
              shape: "arrowDown" as const,
              text: fmt.pct(t.return_pct, 0),
              size: 1,
            }]),
      ]),
      ...positions.map((p): SeriesMarker<UTCTimestamp> => ({
        time: toTime(p.entry_ts), position: "belowBar", color: C.ink, shape: "circle", text: "sua compra", size: 1,
      })),
    ].toSorted((a, b) => a.time - b.time);
    createSeriesMarkers(price, markers);

    chart.subscribeCrosshairMove((param) => {
      const time = param.time === undefined ? undefined : (param.time as UTCTimestamp);
      const point = param.point;
      if (time === undefined || point === undefined) {
        setTip(null);
        return;
      }
      const day = fmt.day(new Date(time * 1000));
      const x = Math.max(0, Math.min(point.x + 14, el.clientWidth - TIP_WIDTH));
      const f = estimates.get(time);
      if (f !== undefined) {
        setTip({
          x,
          title: `${day} (estimativa)`,
          lines: [
            `Faixa de ${f.horizon_days === 1 ? "1 dia" : `${f.horizon_days} dias`}: ${fmt.price(f.p10_price)} a ${fmt.price(f.p90_price)}`,
            `Valor do meio (P50): ${fmt.price(f.p50_price)}`,
            "Não é dado real: é uma estimativa.",
          ],
          source: `Modelo estatístico (${f.method.toLowerCase().replace(/_/g, " ")}), avaliado em ${f.n_eval} janelas de teste`,
          estimate: true,
        });
        return;
      }
      const h = byTime.get(time);
      if (h === undefined) {
        setTip(null);
        return;
      }
      setTip({
        x,
        title: day,
        lines: [
          `Preço de fechamento: ${fmt.price(h.close)}`,
          `Média de 90 dias: ${fmt.price(h.sma_90)}`,
          `Média de 200 dias: ${fmt.price(h.sma_200)}`,
        ],
        source: `${SOURCE_PRICE}; médias calculadas aqui`,
        estimate: false,
      });
    });

    if (last !== undefined && estimates.size > 0) {
      // Com previsão, o foco é o presente: 2 anos de histórico e a faixa à direita (o resto fica a um arrasto de distância).
      const end = toTime(last.timestamp);
      chart.timeScale().setVisibleRange({ from: (end - 730 * DAY_S) as UTCTimestamp, to: (end + 45 * DAY_S) as UTCTimestamp });
    } else {
      chart.timeScale().fitContent();
    }
    return () => chart.remove();
  }, [history, trades, positions, forecast, withForecast, height]);

  return (
    <figure>
      <figcaption className="mb-1.5 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-[12px]">
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-0.5 w-4 bg-series-price" />
          Preço de fechamento
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-0.5 w-4 bg-series-average" />
          Média de 90 dias
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-0.5 w-4 bg-series-trend" />
          <Term id="sma200">Média de 200 dias</Term>
        </span>
        {withForecast && (
          <span className="flex items-center gap-2">
            <span aria-hidden className="inline-block w-4 border-t-2 border-dashed border-series-price opacity-60" />
            Estimativa (<Term id="faixa">faixa P10 a P90</Term>)
          </span>
        )}
      </figcaption>
      <div className="relative">
        <div ref={container} className="w-full" style={{ height }} />
        {tip !== null && (
          <div
            role="status"
            className={`pointer-events-none absolute top-2 z-10 rounded-md border bg-surface p-3 text-[13px] ${tip.estimate ? "border-dashed border-series-price" : "border-hairline"}`}
            style={{ left: tip.x, width: TIP_WIDTH }}
          >
            <p className="font-medium">{tip.title}</p>
            {tip.lines.map((l) => <p key={l} className="num">{l}</p>)}
            <p className="mt-1 text-muted">Fonte: {tip.source}</p>
          </div>
        )}
      </div>
      <Collapsible summary="Como ler o gráfico" className="mt-1.5">
        Setas azuis para cima: dias em que a regra mandou comprar. Setas para baixo: quando mandou vender, com o resultado (verde lucro,
        vermelho perda). Círculo preto: suas compras. O eixo de preço é proporcional: a mesma distância vertical é a mesma variação em %.
        {withForecast && " Linhas tracejadas à direita são estimativas, não preços reais. Arraste o gráfico para ver todo o histórico."}
      </Collapsible>
    </figure>
  );
}
