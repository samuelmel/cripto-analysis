import type { Dashboard, Stage } from "../types/signals";
import { RECOMMENDED_SYMBOLS } from "./coins";
import { coinName, fmt, fngLabel, fngTone, signTone, type Tone } from "./analytics";
import { STATUS_TEXT, TREND_TEXT, VOL_TEXT, latestRegime, trendRuns } from "./regimes";
import { REGIME_LABEL, brl } from "./selection";

/* Indicadores da faixa superior. Cada um sai de um campo que o pipeline já publica (recommendation, daily_signals,
   positions, market_regimes); o que não existe vira "—", nunca um número inventado. */

export interface Kpi {
  readonly key: string;
  readonly label: string;
  readonly value: string;
  readonly note: string;
  readonly tone: Tone;
}

const STAGE_SHORT: Readonly<Record<Stage, string>> = { COMPRAR: "comprar", PREPARAR: "de olho", NEUTRO: "fora", INDISPONÍVEL: "sem dados" };

const sum = (xs: readonly (number | null)[]): number | null =>
  xs.length === 0 || xs.some((x) => x === null) ? null : xs.reduce<number>((a, b) => a + (b ?? 0), 0);

export function buildKpis(data: Dashboard): readonly Kpi[] {
  const { recommendation: rec, signals, positions, marketRegimes } = data;
  const regime = REGIME_LABEL[rec.regime];
  const btc = signals.find((s) => s.symbol === "BTC/USDT");
  const core = signals.filter((s) => RECOMMENDED_SYMBOLS.has(s.symbol)).toSorted((a, b) => a.symbol.localeCompare(b.symbol));

  const latest = latestRegime(marketRegimes);
  const runs = trendRuns(marketRegimes);
  const since = runs.at(-1);
  const experimental: Kpi =
    latest === null
      ? { key: "regime", label: "Regime do BTC (experimental)", value: "—", note: "market_regimes.parquet ausente", tone: "neutral" }
      : latest.status !== "OK" || latest.trend_regime === "INDISPONIVEL"
      ? { key: "regime", label: "Regime do BTC (experimental)", value: "Indisponível", note: STATUS_TEXT[latest.status], tone: "warning" }
      : {
          key: "regime",
          label: "Regime do BTC (experimental)",
          value: `${TREND_TEXT[latest.trend_regime].text}, vol. ${VOL_TEXT[latest.vol_regime].text}`,
          note: since === undefined ? "Só descrição, não gera sinal" : `Desde ${fmt.day(since.start)} (${since.days} d)`,
          tone: TREND_TEXT[latest.trend_regime].tone,
        };

  const value = sum(positions.map((p) => p.value_usd));
  const pnl = sum(positions.map((p) => p.pnl_usd));
  const stageTone: Tone = core.some((s) => s.stage === "COMPRAR") ? "good" : core.some((s) => s.stage === "INDISPONÍVEL") ? "warning" : "neutral";
  const fng = signals[0]?.fng_value ?? null;
  const unallocatedPct = rec.budget_brl > 0 ? (rec.total_brl / rec.budget_brl) * 100 : null;

  return [
    { key: "mercado", label: "Mercado (regra de risco)", value: regime.text, note: btc === undefined ? "Sem BTC" : `BTC ${fmt.price(btc.close)}`, tone: regime.tone },
    experimental,
    { key: "moedas", label: "Moedas analisadas", value: `${rec.n_analyzed}`, note: `${rec.n_candidates} candidatas, ${rec.n_funded} com aporte`, tone: "neutral" },
    {
      key: "aporte", label: "Aporte sugerido", value: brl(rec.total_brl),
      note: `de ${brl(rec.budget_brl)}${unallocatedPct === null ? "" : `, ${fmt.num(unallocatedPct, 0)}% do orçamento`}`,
      tone: rec.total_brl > 0 ? "signal" : "neutral",
    },
    {
      key: "posicoes", label: "Suas posições",
      value: positions.length === 0 ? "Nenhuma" : `${positions.length}`,
      note: positions.length === 0 ? "Nada registrado" : `${fmt.usd(value)}, resultado ${fmt.usd(pnl)}`,
      tone: positions.length === 0 ? "neutral" : signTone(pnl),
    },
    {
      key: "regra", label: "Regra principal (SMA 200)",
      value: core.map((s) => `${coinName(s.symbol)} ${STAGE_SHORT[s.stage]}`).join(", ") || "—",
      note: "Média de 200 dias, só BTC e ETH", tone: stageTone,
    },
    {
      key: "risco", label: "Risco do BTC",
      value: btc?.vol_90d_pct == null ? "—" : `${fmt.num(btc.vol_90d_pct, 0)}% a.a.`,
      note: btc?.drawdown_now_pct == null ? "Volatilidade de 90 dias" : `${fmt.pct(btc.drawdown_now_pct, 0)} do topo de 180 d`,
      tone: btc?.vol_90d_pct != null && btc.vol_90d_pct > 90 ? "warning" : "neutral",
    },
    { key: "humor", label: "Humor do mercado", value: fng === null ? "—" : `${fng}`, note: fng === null ? "Sem leitura" : `${fngLabel(signals[0]?.fng_classification ?? null)} (0 pânico a 100 euforia)`, tone: fngTone(fng) },
  ];
}
