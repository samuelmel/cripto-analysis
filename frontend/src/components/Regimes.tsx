import { fmt } from "../data/analytics";
import {
  STATUS_TEXT,
  TREND_COLOR,
  TREND_TEXT,
  VOL_COLOR,
  VOL_TEXT,
  highVolShare,
  latestRegime,
  trendRuns,
  trendShares,
  trendSwitches,
  volRuns,
  type RegimeRun,
} from "../data/regimes";
import { REGIME_LABEL } from "../data/selection";
import type { MarketRegime } from "../types/signals";
import { Badge, Collapsible, Empty, Panel, TEXT_TONE } from "./ui";

/* Regimes de mercado do BTC (Fase 4): descrição causal e experimental. Não gera sinal, não altera aporte nem regra de
   compra ou venda; o regime de produção continua sendo o "Estado do mercado" (SMA 200 e SMA 50). */

function Ribbon<T extends string>({ runs, color, label }: {
  readonly runs: readonly RegimeRun<T>[];
  readonly color: Readonly<Record<T, string>>;
  readonly label: string;
}) {
  return (
    <div role="img" aria-label={label} className="flex h-4 w-full overflow-hidden rounded-sm bg-ground">
      {runs.map((r) => (
        <span
          key={`${r.start.getTime()}:${r.label}`}
          title={`${r.label.toLowerCase()}: ${fmt.day(r.start)} a ${fmt.day(r.end)} (${r.days} dias)`}
          style={{ flexGrow: r.days, flexBasis: 0, backgroundColor: color[r.label] }}
        />
      ))}
    </div>
  );
}

/** Marcas de ano sob a faixa, proporcionais às datas. */
function YearAxis({ start, end }: { readonly start: Date; readonly end: Date }) {
  const span = end.getTime() - start.getTime();
  const years: number[] = [];
  for (let y = start.getUTCFullYear() + 1; y <= end.getUTCFullYear(); y++) years.push(y);
  return (
    <div aria-hidden className="relative mt-0.5 h-4 text-[11px] text-muted">
      {years.filter((y) => y % 2 === 0 || years.length < 6).map((y) => (
        <span key={y} className="absolute -translate-x-1/2" style={{ left: `${((Date.UTC(y, 0, 1) - start.getTime()) / span) * 100}%` }}>{y}</span>
      ))}
    </div>
  );
}

function Cell({ label, value, note, tone = "neutral" }: {
  readonly label: string;
  readonly value: string;
  readonly note?: string | undefined;
  readonly tone?: "good" | "critical" | "warning" | "neutral" | "signal";
}) {
  return (
    <div>
      <p className="text-[12px] text-muted">{label}</p>
      <p className={`num text-[16px] font-semibold leading-tight ${TEXT_TONE[tone]}`}>{value}</p>
      {note !== undefined && <p className="text-[12px] text-muted">{note}</p>}
    </div>
  );
}

export function RegimesPanel({ rows }: { readonly rows: readonly MarketRegime[] }) {
  const last = latestRegime(rows);
  const first = rows[0];
  if (last === null || first === undefined) {
    return (
      <Panel id="regimes" title="Regimes de mercado do BTC" note="experimental">
        <Empty title="O arquivo de regimes ainda não existe (market_regimes.parquet).">
          Ele é gerado pelo pipeline junto com a análise. Rode no terminal e recarregue a página:
          <pre className="mt-2 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[12px] text-ink">uv run python -m src.pipeline --offline</pre>
        </Empty>
      </Panel>
    );
  }
  const trend = TREND_TEXT[last.trend_regime];
  const runs = trendRuns(rows);
  const vRuns = volRuns(rows);
  const current = runs.at(-1);
  const shares = trendShares(rows);
  const high = highVolShare(rows);
  const ok = last.status === "OK";
  const legacy = last.legacy_regime === null ? null : REGIME_LABEL[last.legacy_regime];
  return (
    <div className="grid gap-3 xl:grid-cols-12">
      <Panel
        id="regimes"
        title="Regimes de mercado do BTC"
        note="experimental, só descrição: não gera sinal nem altera aporte, compra ou venda"
        className="xl:col-span-12"
        actions={<Badge tone="neutral">{last.classifier_version}, parâmetros {last.params_hash.slice(0, 8)}</Badge>}
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4 xl:grid-cols-8">
          <Cell label="Tendência hoje" value={ok ? trend.text : "Indisponível"} tone={ok ? trend.tone : "warning"} note={ok ? (current === undefined ? undefined : `desde ${fmt.day(current.start)} (${current.days} d)`) : STATUS_TEXT[last.status]} />
          <Cell label="Volatilidade" value={last.vol_regime === "INDISPONIVEL" ? "indisponível" : VOL_TEXT[last.vol_regime].text} tone={VOL_TEXT[last.vol_regime].tone} note={last.vol_rank_pct === null ? STATUS_TEXT[last.vol_status] : `percentil ${fmt.num(last.vol_rank_pct, 0)} do passado`} />
          <Cell label="Preço vs média 200" value={fmt.pct(last.dist_ma_pct)} note="distância do fechamento" />
          <Cell label="Inclinação da média" value={fmt.pct(last.slope_ma_pct)} note="variação em 30 dias" />
          <Cell label="Volatilidade anual" value={last.vol_ann_pct === null ? "—" : `${fmt.num(last.vol_ann_pct, 0)}%`} note="retornos de 30 dias" />
          <Cell label="Estado de mercado (produção)" value={legacy === null ? "—" : legacy.text} note="regra SMA 200/50, para comparar" />
          <Cell label="Trocas de tendência" value={`${trendSwitches(rows)}`} note={`em ${rows.length.toLocaleString("pt-BR")} dias`} />
          <Cell label="Válido a partir de" value={fmt.day(last.known_at)} note="fechamento do candle (known_at)" />
        </div>

        <div className="mt-4">
          <p className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
            <span className="font-medium">Tendência ao longo do tempo</span>
            {(["ALTA", "BAIXA", "MISTO", "LATERAL"] as const).map((k) => (
              <span key={k} className="flex items-center gap-1 text-muted">
                <span aria-hidden className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: TREND_COLOR[k] }} />
                {TREND_TEXT[k].text}
              </span>
            ))}
            <span className="flex items-center gap-1 text-muted"><span aria-hidden className="inline-block h-2 w-2 rounded-sm bg-hairline" />sem classificação</span>
          </p>
          <Ribbon runs={runs} color={TREND_COLOR} label="Regime de tendência do BTC de cada dia" />
          <p className="mb-1 mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
            <span className="font-medium">Volatilidade</span>
            <span className="flex items-center gap-1 text-muted"><span aria-hidden className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: VOL_COLOR.ALTA }} />alta (acima do percentil 80 do passado)</span>
          </p>
          <Ribbon runs={vRuns} color={VOL_COLOR} label="Regime de volatilidade do BTC de cada dia" />
          <YearAxis start={first.timestamp} end={last.timestamp} />
        </div>
      </Panel>

      <Panel id="regimes-freq" title="Quanto tempo em cada regime" note="dias classificados" className="xl:col-span-5">
        <ul className="space-y-1.5">
          {shares.map((s) => (
            <li key={s.label} className="grid grid-cols-[5rem_1fr_7rem] items-center gap-2 text-[12px]">
              <span className="font-medium">{TREND_TEXT[s.label].text}</span>
              <span aria-hidden className="block h-2 rounded-sm bg-ground">
                <span className="block h-full rounded-sm" style={{ width: `${s.pct}%`, backgroundColor: TREND_COLOR[s.label] }} />
              </span>
              <span className="num text-right text-muted">{fmt.num(s.pct, 1)}%, {s.days.toLocaleString("pt-BR")} d</span>
            </li>
          ))}
          <li className="grid grid-cols-[5rem_1fr_7rem] items-center gap-2 text-[12px]">
            <span className="font-medium">Vol. alta</span>
            <span aria-hidden className="block h-2 rounded-sm bg-ground">
              <span className="block h-full rounded-sm" style={{ width: `${high ?? 0}%`, backgroundColor: VOL_COLOR.ALTA }} />
            </span>
            <span className="num text-right text-muted">{high === null ? "—" : `${fmt.num(high, 1)}%`}</span>
          </li>
        </ul>
      </Panel>

      <Panel id="regimes-limites" title="Limitações conhecidas" className="xl:col-span-7">
        <ul className="list-disc space-y-1 pl-5 text-[12px] text-muted">
          <li>Uma única série (BTC) e uma única história de mercado; poucos episódios por regime.</li>
          <li>Forte dependência da janela da média: 150 ou 250 dias em vez de 200 mudam cerca de 17% a 20% dos rótulos.</li>
          <li>A volatilidade é relativa ao passado do próprio BTC: 2018 a 2021 pesam muito e a volatilidade recente quase nunca é "alta".</li>
          <li>A confirmação de 5 dias atrasa as viradas (custo explícito de estabilidade).</li>
          <li>Não há evidência de que os regimes separem retornos futuros, e a seleção de estratégias por regime não foi sustentada na pesquisa.</li>
        </ul>
        <Collapsible summary="Como o regime é definido" className="mt-2">
          Tendência: distância do preço à média de 200 dias (zona morta de ±5%) e inclinação dessa média em 30 dias (±2%). Um estado novo só vale
          depois de 5 dias seguidos iguais. Volatilidade: desvio dos retornos de 30 dias comparado ao passado estrito do próprio ativo, com histerese
          (entra acima do percentil 80, sai abaixo do 70). Dados ausentes ou inválidos viram "indisponível", nunca zero. Detalhes em docs/regimes.md.
        </Collapsible>
      </Panel>
    </div>
  );
}
