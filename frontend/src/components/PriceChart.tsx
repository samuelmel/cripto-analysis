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
import { distanceFromAverage, fmt } from "../data/analytics";
import type { HistoryPoint, Position, Trade } from "../types/signals";

/* Cores do DESIGN.md (validadas com validate_palette.js). O canvas não lê CSS vars. */
const C = {
  surface: "#fcfcfb",
  muted: "#55544f",
  grid: "#ecebe6",
  axis: "#e1e0d9",
  price: "#2a78d6",
  average: "#eb6834",
  trend: "#4a3aa7",
  good: "#0ca30c",
  critical: "#d03b3b",
  ink: "#121417",
} as const;

const toTime = (d: Date): UTCTimestamp => Math.floor(d.getTime() / 1000) as UTCTimestamp;

interface Readout {
  readonly date: Date;
  readonly close: number;
  readonly sma: number | null;
  readonly sma200: number | null;
}

interface Props {
  readonly history: readonly HistoryPoint[];
  readonly trades: readonly Trade[];
  readonly positions: readonly Position[];
}

/** Preço e médias de 90 e 200 dias, com entradas e saídas da regra de tendência e suas compras. */
export function PriceChart({ history, trades, positions }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const last = history.at(-1);
  const [readout, setReadout] = useState<Readout | null>(null);
  const shown: Readout | null = readout ?? (last === undefined ? null : { date: last.timestamp, close: last.close, sma: last.sma_90, sma200: last.sma_200 });

  useEffect(() => {
    const el = container.current;
    if (el === null) return;
    const byTime = new Map(history.map((h) => [toTime(h.timestamp), h]));

    const chart: IChartApi = createChart(el, {
      height: 360,
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

    const price = chart.addSeries(LineSeries, { color: C.price, lineWidth: 2, priceLineVisible: false });
    price.setData(history.map((h) => ({ time: toTime(h.timestamp), value: h.close })));

    const average = chart.addSeries(LineSeries, {
      color: C.average, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    average.setData(history.flatMap((h) => (h.sma_90 === null ? [] : [{ time: toTime(h.timestamp), value: h.sma_90 }])));

    const trend = chart.addSeries(LineSeries, {
      color: C.trend, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    trend.setData(history.flatMap((h) => (h.sma_200 === null ? [] : [{ time: toTime(h.timestamp), value: h.sma_200 }])));

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
      const h = param.time === undefined ? undefined : byTime.get(param.time as UTCTimestamp);
      setReadout(h === undefined ? null : { date: h.timestamp, close: h.close, sma: h.sma_90, sma200: h.sma_200 });
    });

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [history, trades, positions]);

  const dist = shown === null ? null : distanceFromAverage(shown.close, shown.sma200);

  return (
    <figure>
      <figcaption className="mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-[13px]">
        <span className="text-muted">{shown === null ? "—" : fmt.day(shown.date)}</span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-0.5 w-4 bg-series-price" />
          Preço <strong className="num font-medium">{fmt.price(shown?.close ?? null)}</strong>
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-0.5 w-4 bg-series-average" />
          Média de 90 dias <strong className="num font-medium">{fmt.price(shown?.sma ?? null)}</strong>
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-0.5 w-4 bg-series-trend" />
          Média de 200 dias <strong className="num font-medium">{fmt.price(shown?.sma200 ?? null)}</strong>
        </span>
        <span className="text-muted">
          {dist === null ? "" : `preço ${fmt.num(Math.abs(dist), 1)}% ${dist < 0 ? "abaixo" : "acima"} da média de 200 dias`}
        </span>
      </figcaption>
      <div ref={container} className="w-full" />
      <p className="mt-3 text-[13px] text-muted">
        Setas azuis para cima: dias em que a regra mandou comprar (preço e Bitcoin acima da média de 200 dias). Setas para baixo:
        quando a regra mandou vender, com o resultado (verde lucro, vermelho perda). A linha violeta é a média de 200 dias, a que decide tudo. Círculo preto: suas compras. O eixo de preço é proporcional: a mesma
        distância vertical representa a mesma variação em %. Passe o mouse para ver o preço de cada dia.
      </p>
    </figure>
  );
}
