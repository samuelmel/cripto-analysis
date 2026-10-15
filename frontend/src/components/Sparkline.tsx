import { fmt } from "../data/analytics";

const W = 96;
const H = 28;
const PAD = 3;

/** Mini-gráfico de uma série só (sem legenda: o título da coluna diz o que é). */
export function Sparkline({ values, label }: { readonly values: readonly number[]; readonly label: string }) {
  if (values.length < 2) return <span className="text-muted">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i: number): number => PAD + (i / (values.length - 1)) * (W - 2 * PAD);
  const y = (v: number): number => PAD + (1 - (v - min) / span) * (H - 2 * PAD);
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const first = values[0] ?? 0;
  const last = values.at(-1) ?? 0;
  const change = first === 0 ? null : (last / first - 1) * 100;
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label}: ${fmt.pct(change)} em 90 dias`}>
      <polyline points={points} fill="none" stroke="var(--color-series-price)" strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={x(values.length - 1)} cy={y(last)} r={2.5} fill="var(--color-series-price)" />
    </svg>
  );
}
