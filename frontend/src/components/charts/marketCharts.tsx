import type { ReactNode } from "react";

import { dateShort, number, pct, price } from "../../lib/format";
import type { Candle, Performance } from "../../schemas/api";
import { EChart } from "./EChart";

const AXIS = "#8a887e";
const HAIRLINE = "#dcdad1";
const INK = "#151613";

const axisDate = (value: string): string =>
  new Date(value).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", timeZone: "UTC" }).replace(".", "");

export function CloseLineChart({
  candles,
  height = 300,
  color = "#0d6b63",
}: {
  candles: readonly Candle[];
  height?: number;
  color?: string;
}): ReactNode {
  const option = {
    animationDuration: 420,
    grid: { left: 8, right: 16, top: 18, bottom: 26, containLabel: true },
    tooltip: {
      trigger: "axis",
      borderColor: HAIRLINE,
      backgroundColor: "#fbfaf7",
      textStyle: { color: INK, fontFamily: "IBM Plex Sans", fontSize: 12 },
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: candles.map((candle) => axisDate(candle.timestamp)),
      axisLine: { lineStyle: { color: HAIRLINE } },
      axisTick: { show: false },
      axisLabel: { color: AXIS, fontSize: 10, interval: Math.max(0, Math.floor(candles.length / 6)) },
    },
    yAxis: {
      type: "value",
      scale: true,
      splitLine: { lineStyle: { color: HAIRLINE, type: "dashed" } },
      axisLabel: { color: AXIS, fontSize: 10 },
    },
    series: [
      {
        type: "line",
        data: candles.map((candle) => candle.close),
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 1.6, color },
        itemStyle: { color },
        areaStyle: { color, opacity: 0.07 },
      },
    ],
  };
  return <EChart option={option} height={height} label="Série histórica de fechamento" />;
}

export function PerformanceChart({ rows, height = 270 }: { rows: readonly Performance[]; height?: number }): ReactNode {
  const periods = ["TREINO", "TESTE"] as const;
  const trend = periods.map((period) => rows.find((row) => row.strategy === "TENDENCIA" && row.period === period)?.total_return_pct ?? 0);
  const hold = periods.map(
    (period) => rows.find((row) => row.strategy === "COMPRAR_E_SEGURAR" && row.period === period)?.total_return_pct ?? 0,
  );
  const option = {
    animationDuration: 420,
    grid: { left: 8, right: 14, top: 40, bottom: 20, containLabel: true },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: "#5d5c55", fontFamily: "IBM Plex Sans", fontSize: 11 },
      itemWidth: 10,
      itemHeight: 8,
    },
    tooltip: {
      trigger: "axis",
      borderColor: HAIRLINE,
      backgroundColor: "#fbfaf7",
      textStyle: { color: INK, fontFamily: "IBM Plex Sans", fontSize: 12 },
      valueFormatter: (value: string | number) => `${number(Number(value), 1)}%`,
    },
    xAxis: {
      type: "category",
      data: ["Treino 2018–2022", "Teste 2023–2026"],
      axisLine: { lineStyle: { color: HAIRLINE } },
      axisTick: { show: false },
      axisLabel: { color: AXIS, fontSize: 11 },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: HAIRLINE, type: "dashed" } },
      axisLabel: { color: AXIS, fontSize: 10, formatter: "{value}%" },
    },
    series: [
      {
        name: "Regra SMA 200",
        type: "bar",
        data: trend,
        barMaxWidth: 30,
        itemStyle: { color: "#0d6b63", borderRadius: [3, 3, 0, 0] },
      },
      {
        name: "Comprar e segurar",
        type: "bar",
        data: hold,
        barMaxWidth: 30,
        itemStyle: { color: "#b05e34", borderRadius: [3, 3, 0, 0] },
      },
    ],
  };
  return <EChart option={option} height={height} label="Retorno acumulado da regra de tendência contra comprar e segurar" />;
}

export function ForecastBand({
  low,
  mid,
  high,
  last,
  horizon,
  method,
}: {
  low: number;
  mid: number;
  high: number;
  last: number;
  horizon: number;
  method: string;
}): ReactNode {
  const spread = Math.max(high - low, 1);
  const clamp = (value: number): number => Math.min(100, Math.max(0, ((value - low) / spread) * 100));
  const midPos = clamp(mid);
  const lastPos = clamp(last);
  return (
    <div className="border border-hairline bg-surface p-4">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-faint">
          {horizon === 1 ? "1 dia" : `${horizon} dias`}
        </div>
        <div className="text-[11px] text-faint">{method}</div>
      </div>
      <div className="num mt-2 text-[18px] font-medium text-ink">{price(mid)}</div>
      <div className="mt-3 h-1.5 rounded-full bg-sunken">
        <div
          className="h-1.5 rounded-full bg-signal/25"
          style={{ marginLeft: `${clamp(low)}%`, width: `${Math.max(2, clamp(high) - clamp(low))}%` }}
        />
      </div>
      <div className="relative mt-1 h-3 text-[10px] text-faint">
        <span className="absolute -translate-x-1/2" style={{ left: `${midPos}%` }}>
          mediana
        </span>
        <span className="absolute -translate-x-1/2" style={{ left: `${lastPos}%` }}>
          hoje
        </span>
      </div>
      <div className="num mt-2 flex justify-between gap-2 text-[11px] text-muted">
        <span>{price(low)}</span>
        <span className="text-faint">{pct(((mid - last) / last) * 100)}</span>
        <span>{price(high)}</span>
      </div>
      <div className="mt-2 text-[10px] text-faint">Faixa P10–P90 · não é previsão de direção</div>
    </div>
  );
}

export function MiniSparkline({ values, width = 110, height = 28 }: { values: readonly number[]; width?: number; height?: number }): ReactNode {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="overflow-visible">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function lastCandleLabel(candles: readonly Candle[]): string {
  const last = candles.at(-1);
  return last ? `${dateShort(last.timestamp)} · ${price(last.close)}` : "sem candles";
}
