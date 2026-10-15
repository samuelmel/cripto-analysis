import {
  ColorType,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { HistoryPoint, Position, Trade } from "../types/signals";

const toTime = (d: Date): UTCTimestamp => Math.floor(d.getTime() / 1000) as UTCTimestamp;

interface Props {
  readonly history: readonly HistoryPoint[];
  readonly trades: readonly Trade[];
  readonly positions: readonly Position[];
}

/** Preço e SMA 90 com as entradas/saídas do sinal histórico e suas compras marcadas. */
export function PriceChart({ history, trades, positions }: Props) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = container.current;
    if (el === null) return;
    const chart: IChartApi = createChart(el, {
      height: 380,
      layout: { background: { type: ColorType.Solid, color: "#000000" }, textColor: "#a3a3a3", fontFamily: "monospace" },
      grid: { vertLines: { color: "#171717" }, horzLines: { color: "#171717" } },
      rightPriceScale: { borderColor: "#404040" },
      timeScale: { borderColor: "#404040" },
      autoSize: true,
    });

    const price = chart.addSeries(LineSeries, { color: "#4ade80", lineWidth: 2, priceLineVisible: false });
    price.setData(history.map((h) => ({ time: toTime(h.timestamp), value: h.close })));

    const sma = chart.addSeries(LineSeries, { color: "#737373", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    sma.setData(history.flatMap((h) => (h.sma_90 === null ? [] : [{ time: toTime(h.timestamp), value: h.sma_90 }])));

    const markers: SeriesMarker<UTCTimestamp>[] = [
      ...trades.flatMap((t): SeriesMarker<UTCTimestamp>[] => [
        { time: toTime(t.entry_ts), position: "belowBar", color: "#22c55e", shape: "arrowUp", text: "C" },
        ...(t.exit_ts === null
          ? []
          : [{
              time: toTime(t.exit_ts),
              position: "aboveBar" as const,
              color: (t.return_pct ?? 0) > 0 ? "#facc15" : "#ef4444",
              shape: "arrowDown" as const,
              text: t.exit_reason ?? "",
            }]),
      ]),
      ...positions.map((p): SeriesMarker<UTCTimestamp> => ({
        time: toTime(p.entry_ts), position: "belowBar", color: "#ffffff", shape: "circle", text: "você",
      })),
    ].toSorted((a, b) => a.time - b.time);
    createSeriesMarkers(price, markers);

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [history, trades, positions]);

  return <div ref={container} className="w-full" />;
}
