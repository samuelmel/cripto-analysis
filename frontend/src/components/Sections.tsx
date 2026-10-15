import { Gauge, HandCoins, Scales, TrendDown, TrendUp } from "@phosphor-icons/react";
import {
  PERIOD_NAME,
  REASON_SHORT,
  RULE_TEXT,
  STAGE_LABEL,
  STRATEGY_NAME,
  byReason,
  coinName,
  distanceFromAverage,
  fmt,
  performanceOf,
  periodYears,
  signTone,
  summarize,
  trendVerdict,
  type Tone,
  type TrendVerdict,
  type Verdict,
} from "../data/analytics";
import {
  EXIT_REASONS,
  type DailySignal,
  type ExitReason,
  type Performance,
  type Period,
  type Portfolio,
  type Strategy,
  type Trade,
} from "../types/signals";
import { CoinLabel } from "./CoinLabel";
import { REASON_ICON, STAGE_ICON, VERDICT_ICON } from "./icons";
import { Sparkline } from "./Sparkline";
import { Badge, Block, Figure, TEXT_TONE, Table, cell, numCell } from "./ui";

/* ---------- hoje ---------- */

const VERDICT_BORDER: Record<Tone, string> = {
  good: "border-good-mark",
  critical: "border-critical-mark",
  warning: "border-warning-mark",
  neutral: "border-hairline",
  signal: "border-signal",
};

const VERDICT_ICON_TONE: Record<Tone, string> = {
  good: "text-good",
  critical: "text-critical",
  warning: "text-warning",
  neutral: "text-good",
  signal: "text-signal",
};

export function TodayPanel({ verdict, fng, fngText, fngTone, asOf }: {
  readonly verdict: Verdict;
  readonly fng: number | null;
  readonly fngText: string;
  readonly fngTone: Tone;
  readonly asOf: string;
}) {
  const Icon = VERDICT_ICON[verdict.tone];
  return (
    <div className="grid gap-6 md:grid-cols-[1fr_auto]">
      <div className={`flex gap-4 rounded-md border-2 bg-surface p-6 ${VERDICT_BORDER[verdict.tone]}`}>
        <Icon size={40} weight="duotone" className={`shrink-0 ${VERDICT_ICON_TONE[verdict.tone]}`} aria-hidden />
        <div>
          <p className="text-[13px] text-muted">Hoje, com o fechamento de {asOf}</p>
          <p className="mt-1 text-[28px] font-semibold leading-tight tracking-[-0.01em]">{verdict.headline}</p>
          <ul className="mt-3 space-y-1">
            {verdict.details.map((d) => <li key={d}>{d}</li>)}
          </ul>
        </div>
      </div>
      <Block className="md:w-64">
        <div className="flex items-start justify-between gap-3">
          <Figure
            label="Humor do mercado"
            value={fng === null ? "—" : `${fng}`}
            tone={fngTone}
            note={`${fngText} — de 0 (pânico) a 100 (euforia)`}
          />
          <Gauge size={28} className="shrink-0 text-muted" aria-hidden />
        </div>
        <FngScale value={fng} />
      </Block>
    </div>
  );
}

/** Régua 0–100 do Fear & Greed com a posição de hoje. */
function FngScale({ value }: { readonly value: number | null }) {
  if (value === null) return null;
  return (
    <div className="mt-4" aria-hidden>
      <div className="relative h-2 rounded-sm bg-ground">
        {/* faixa de pânico (< 25): só um aviso, a regra de compra não usa o humor do mercado */}
        <span className="absolute inset-y-0 left-0 w-1/4 rounded-l-sm bg-critical-bg" />
        {[25, 50, 75].map((t) => <span key={t} className="absolute inset-y-0 w-px bg-hairline" style={{ left: `${t}%` }} />)}
        <span className="absolute -top-1 h-4 w-1 -translate-x-1/2 rounded-sm bg-ink" style={{ left: `${Math.min(Math.max(value, 0), 100)}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[12px] text-muted">
        <span>pânico</span>
        <span>neutro</span>
        <span>euforia</span>
      </div>
    </div>
  );
}

/* ---------- moedas ---------- */

function DistanceBar({ pct }: { readonly pct: number | null }) {
  if (pct === null) return <span className="text-muted">—</span>;
  const width = (Math.min(Math.abs(pct), 60) / 60) * 100; // ±60% enche metade da barra
  const below = pct < 0;
  return (
    <span className="flex items-center justify-end gap-3">
      <span className="num">{fmt.pct(pct)}</span>
      <span aria-hidden className="relative block h-2 w-24 rounded-sm bg-ground">
        <span className="absolute inset-y-0 left-1/2 w-px bg-hairline" />
        <span
          className={`absolute inset-y-0 rounded-sm ${below ? "right-1/2 bg-critical-mark" : "left-1/2 bg-series-price"}`}
          style={{ width: `${width / 2}%` }}
        />
      </span>
    </span>
  );
}

function Trend({ pct }: { readonly pct: number | null }) {
  if (pct === null) return <span className="text-muted">sem dados</span>;
  const Icon = pct >= 0 ? TrendUp : TrendDown;
  return (
    <span className={`flex items-center gap-1.5 ${pct >= 0 ? "text-good" : "text-muted"}`}>
      <Icon size={16} aria-hidden />
      {pct >= 0 ? "em alta" : "em baixa"}
    </span>
  );
}

export function MarketTable({ rows, sparks, recommended, selected, onSelect }: {
  readonly rows: readonly DailySignal[];
  readonly sparks: ReadonlyMap<string, readonly number[]>;
  readonly recommended: ReadonlySet<string>;
  readonly selected: string;
  readonly onSelect: (symbol: string) => void;
}) {
  return (
    <Table
      caption="Todas as moedas monitoradas e a recomendação da regra de tendência para Bitcoin e Ethereum"
      columns={[
        { label: "Moeda" }, { label: "O que fazer" }, { label: "Preço", numeric: true }, { label: "Últimos 90 dias" },
        { label: "Distância da média de 200 dias", numeric: true }, { label: "Tendência da moeda" },
      ]}
    >
      {rows.map((s) => {
        const stage = STAGE_LABEL[s.stage];
        const StageIcon = STAGE_ICON[s.stage];
        const isSelected = s.symbol === selected;
        const distance = distanceFromAverage(s.close, s.sma_200);
        return (
          <tr
            key={s.symbol}
            tabIndex={0}
            aria-selected={isSelected}
            onClick={() => onSelect(s.symbol)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(s.symbol);
              }
            }}
            className={`cursor-pointer border-b border-hairline transition-colors hover:bg-ground ${isSelected ? "bg-signal-bg" : ""}`}
          >
            <td className={cell}>
              <span className="flex items-center gap-2">
                <CoinLabel symbol={s.symbol} detailed />
                {s.alert === "COMPRAR AGORA" && <Badge tone="signal">novo hoje</Badge>}
                {s.alert === "VENDER AGORA" && <Badge tone="critical">saiu da alta</Badge>}
              </span>
            </td>
            <td className={cell}>
              {!recommended.has(s.symbol) ? (
                <span className="text-muted">Só acompanhada</span>
              ) : s.stage === "NEUTRO" ? (
                <span className="text-muted">{stage.text}</span>
              ) : (
                <Badge tone={stage.tone}>
                  <span className="flex items-center gap-1.5">
                    {StageIcon !== null && <StageIcon size={14} aria-hidden />}
                    {stage.text}
                  </span>
                </Badge>
              )}
              {s.panic && <span className="ml-2 text-[13px] text-warning">em pânico</span>}
            </td>
            <td className={numCell}>{fmt.price(s.close)}</td>
            <td className={cell}><Sparkline values={sparks.get(s.symbol) ?? []} label={`Preço de ${coinName(s.symbol)}`} /></td>
            <td className={numCell}><DistanceBar pct={distance} /></td>
            <td className={cell}><Trend pct={distance} /></td>
          </tr>
        );
      })}
    </Table>
  );
}

/* ---------- histórico de uma moeda ---------- */

function ReasonCell({ reason }: { readonly reason: Trade["exit_reason"] }) {
  if (reason === null) return <>—</>;
  const Icon = REASON_ICON[reason];
  return (
    <span className="flex items-center gap-2">
      <Icon size={16} className="text-muted" aria-hidden />
      {REASON_SHORT[reason]}
    </span>
  );
}

export function TradeList({ trades, coin, recommended }: {
  readonly trades: readonly Trade[];
  readonly coin: string;
  readonly recommended: boolean;
}) {
  if (!recommended) {
    return <p className="text-muted">A regra só recomenda comprar Bitcoin e Ethereum. {coin} é apenas acompanhada, então não há operações simuladas.</p>;
  }
  if (trades.length === 0) {
    return <p className="text-muted">A regra nunca mandou comprar {coin} desde o início dos dados.</p>;
  }
  return (
    <Table
      caption={`Cada período em que a regra mandou comprar ou segurar ${coin}`}
      columns={[
        { label: "Entrada em" }, { label: "Preço", numeric: true }, { label: "Venda simulada em" },
        { label: "Motivo" }, { label: "Resultado", numeric: true }, { label: "Dias", numeric: true },
      ]}
    >
      {trades.toSorted((a, b) => b.entry_ts.getTime() - a.entry_ts.getTime()).map((t) => (
        <tr key={t.trade_id} className="border-b border-hairline">
          <td className={cell}>{fmt.day(t.entry_ts)}</td>
          <td className={numCell}>{fmt.price(t.entry_price)}</td>
          <td className={cell}>{t.status === "ABERTA" ? <span className="text-muted">ainda aberta</span> : fmt.day(t.exit_ts)}</td>
          <td className={cell}><ReasonCell reason={t.exit_reason} /></td>
          <td className={`${numCell} ${TEXT_TONE[signTone(t.return_pct)]}`}>{fmt.pct(t.return_pct)}</td>
          <td className={numCell}>{t.days_held ?? "—"}</td>
        </tr>
      ))}
    </Table>
  );
}

/* ---------- a regra funciona? ---------- */

const STRATEGY_ORDER: readonly Strategy[] = ["TENDENCIA", "COMPRAR_E_SEGURAR", "PANICO"];

function PerformanceTable({ rows, universe, period }: {
  readonly rows: readonly Performance[];
  readonly universe: Portfolio;
  readonly period: Period;
}) {
  const label = `${PERIOD_NAME[period]} (${periodYears(rows, period)})`;
  return (
    <Table
      caption={`Resultado da carteira no período ${label}, com taxa de 0,1% em cada compra e venda`}
      columns={[
        { label }, { label: "Retorno total", numeric: true }, { label: "Por ano", numeric: true },
        { label: "Pior queda", numeric: true }, { label: "Tempo comprado", numeric: true },
      ]}
    >
      {STRATEGY_ORDER.flatMap((strategy) => {
        const p = performanceOf(rows, universe, strategy, period);
        if (p === null) return [];
        return [
          <tr key={strategy} className="border-b border-hairline">
            <td className={`${cell} ${strategy === "TENDENCIA" ? "font-medium" : ""}`}>{STRATEGY_NAME[strategy]}</td>
            <td className={`${numCell} ${TEXT_TONE[signTone(p.total_return_pct)]}`}>{fmt.pct(p.total_return_pct, 0)}</td>
            <td className={`${numCell} ${TEXT_TONE[signTone(p.annual_return_pct)]}`}>{fmt.pct(p.annual_return_pct)}</td>
            <td className={`${numCell} text-critical`}>{fmt.pct(p.max_drawdown_pct)}</td>
            <td className={numCell}>{fmt.num(p.invested_pct, 0)}%</td>
          </tr>,
        ];
      })}
    </Table>
  );
}

const VERDICT_HEADLINE: Record<TrendVerdict, string> = {
  better: "Sim. No passado, a regra de tendência rendeu mais do que comprar e segurar, nos dois períodos.",
  safer: "Em parte. A regra rendeu parecido com comprar e segurar, mas com uma queda bem menor pelo caminho.",
  worse: "Não. No passado, a regra rendeu menos do que comprar e segurar, e a queda não compensou.",
};

export function BacktestPanel({ performance, trades }: {
  readonly performance: readonly Performance[];
  readonly trades: readonly Trade[];
}) {
  const verdict = trendVerdict(performance, "PRINCIPAIS");
  const trend = performanceOf(performance, "PRINCIPAIS", "TENDENCIA", "TESTE");
  const hold = performanceOf(performance, "PRINCIPAIS", "COMPRAR_E_SEGURAR", "TESTE");
  const all = summarize(trades);
  const reasons = byReason(trades);
  return (
    <>
      <Block>
        <p className="flex items-start gap-3 text-lg font-semibold">
          <Scales size={28} weight="duotone" className={`shrink-0 ${verdict === "worse" ? "text-critical" : "text-good"}`} aria-hidden />
          <span>{verdict === null ? "Ainda não há dados suficientes para responder." : VERDICT_HEADLINE[verdict]}</span>
        </p>
        <p className="mt-2 max-w-[72ch] text-muted">
          Simulamos uma carteira com Bitcoin e Ethereum em partes iguais, com taxa de 0,1% a cada compra e venda. A regra foi
          escolhida olhando só o período de treino; o período de teste são anos que a escolha não viu. Comprar e segurar
          significa comprar no começo e nunca vender.
        </p>
        {trend !== null && hold !== null && (
          <div className="mt-6 grid gap-6 sm:grid-cols-2">
            <div className="border-t border-hairline pt-4">
              <p className="font-medium">Pior queda no teste: regra de tendência</p>
              <div className="mt-3">
                <Figure
                  label="Quanto a carteira chegou a perder do topo até o fundo"
                  value={fmt.pct(trend.max_drawdown_pct, 0)}
                  tone="critical"
                  note={`Retorno de ${fmt.pct(trend.total_return_pct, 0)} no período`}
                />
              </div>
            </div>
            <div className="border-t border-hairline pt-4">
              <p className="font-medium">Pior queda no teste: comprar e segurar</p>
              <div className="mt-3">
                <Figure
                  label="Quanto a carteira chegou a perder do topo até o fundo"
                  value={fmt.pct(hold.max_drawdown_pct, 0)}
                  tone="critical"
                  note={`Retorno de ${fmt.pct(hold.total_return_pct, 0)} no período`}
                />
              </div>
            </div>
          </div>
        )}
      </Block>

      <h3 className="mt-8 font-medium">Bitcoin e Ethereum: o que as regras teriam rendido</h3>
      <div className="mt-3 space-y-4">
        <PerformanceTable rows={performance} universe="PRINCIPAIS" period="TREINO" />
        <PerformanceTable rows={performance} universe="PRINCIPAIS" period="TESTE" />
      </div>
      <p className="mt-3 max-w-[72ch] text-[13px] text-muted">
        A regra antiga, comprar quando o mercado entra em pânico, perdeu dinheiro no treino e rendeu pouco no teste.
        Por isso o pânico virou só um aviso.
      </p>

      <h3 className="mt-8 font-medium">E com as 15 moedas?</h3>
      <p className="mt-1 max-w-[72ch] text-muted">
        Aplicada a todas as moedas, a regra continua reduzindo a queda, mas rende bem menos do que comprar e segurar no
        teste. Por isso o painel só recomenda Bitcoin e Ethereum.
      </p>
      <div className="mt-3 space-y-4">
        <PerformanceTable rows={performance} universe="TODAS" period="TREINO" />
        <PerformanceTable rows={performance} universe="TODAS" period="TESTE" />
      </div>

      <h3 className="mt-8 font-medium">Como as compras de Bitcoin e Ethereum terminaram</h3>
      <p className="mt-1 max-w-[72ch] text-muted">
        De {all.count} compras simuladas, {fmt.num(all.winRate, 0)}% terminaram com lucro e o resultado médio foi {fmt.pct(all.mean)}.
        A regra erra muitas vezes com perdas pequenas e acerta algumas vezes com ganhos enormes: é assim que seguir a tendência funciona.
      </p>
      <div className="mt-3">
        <Table
          caption="Operações da regra de tendência agrupadas pelo motivo da venda"
          columns={[
            { label: "Motivo da venda" }, { label: "Operações", numeric: true }, { label: "Com lucro", numeric: true },
            { label: "Resultado médio", numeric: true }, { label: "Pior", numeric: true }, { label: "Melhor", numeric: true },
            { label: "Dias até vender", numeric: true },
          ]}
        >
          {EXIT_REASONS.flatMap((reason) => {
            const x = reasons.get(reason);
            if (x === undefined) return [];
            return [
              <tr key={reason} className="border-b border-hairline">
                <td className={cell}><ReasonCell reason={reason} /></td>
                <td className={numCell}>{x.count}</td>
                <td className={numCell}>{fmt.num(x.winRate, 0)}%</td>
                <td className={`${numCell} ${TEXT_TONE[signTone(x.mean)]}`}>{fmt.pct(x.mean)}</td>
                <td className={`${numCell} ${TEXT_TONE[signTone(x.worst)]}`}>{fmt.pct(x.worst)}</td>
                <td className={`${numCell} ${TEXT_TONE[signTone(x.best)]}`}>{fmt.pct(x.best)}</td>
                <td className={numCell}>{fmt.num(x.meanDays, 0)}</td>
              </tr>,
            ];
          })}
        </Table>
      </div>

      <p className="mt-6 max-w-[72ch] text-[13px] text-muted">
        Limites desta análise: só entram moedas que existem hoje (as que sumiram não aparecem, o que favorece os
        resultados); é uma única história de mercado, com poucos ciclos; não há impostos nem diferença entre o preço
        do fechamento e o que você de fato consegue pagar. O passado não garante o futuro.
      </p>
    </>
  );
}

/* ---------- como funciona ---------- */

export function HowItWorks() {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Block>
        <h3 className="flex items-center gap-2 font-medium"><HandCoins size={22} aria-hidden /> Quando comprar ou segurar</h3>
        <p className="mt-2 text-muted">Vale para Bitcoin e Ethereum. As duas coisas precisam acontecer ao mesmo tempo:</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>O preço da moeda fechou o dia acima da média dos últimos 200 dias. É o sinal de que ela está em tendência de alta.</li>
          <li>O Bitcoin também fechou acima da média dele. Quando o Bitcoin cai, quase tudo cai junto.</li>
        </ul>
        <p className="mt-3 text-muted">
          Enquanto as duas valem, quem não tem pode comprar e quem já tem deve segurar.{" "}
          <strong className="font-medium text-ink">Ficar de olho</strong> é a etapa anterior: o preço está até 3% abaixo
          da média de 200 dias e subindo, perto de cruzá-la.
        </p>
        <p className="mt-3 text-muted">
          As outras 13 moedas aparecem na tabela, mas sem recomendação: o teste mostrou que a regra não compensa nelas.
          O <strong className="font-medium text-ink">pânico</strong> (queda forte com medo no mercado) aparece só como aviso.
          Comprar nele perdeu dinheiro.
        </p>
      </Block>
      <Block>
        <h3 className="font-medium">Quando vender o que você comprou</h3>
        <p className="mt-2 text-muted">A primeira regra que acontecer manda vender:</p>
        <ul className="mt-3 space-y-3">
          {SELL_ORDER.map((r) => {
            const Icon = REASON_ICON[r];
            return (
              <li key={r} className="flex gap-3">
                <Icon size={22} className="mt-0.5 shrink-0 text-muted" aria-hidden />
                <span><strong className="font-medium">{REASON_SHORT[r]}:</strong> {RULE_TEXT[r]}.</span>
              </li>
            );
          })}
        </ul>
        <p className="mt-4 text-muted">
          O pipeline atualiza tudo uma vez por dia, depois que o dia fecha (21h no horário de Brasília). Isto é uma
          ferramenta estatística, não recomendação de investimento.
        </p>
      </Block>
    </div>
  );
}

const SELL_ORDER: readonly ExitReason[] = ["TENDENCIA", "MERCADO", "STOP"];
