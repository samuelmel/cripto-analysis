import { HandCoins, Scales, TrendDown, TrendUp } from "@phosphor-icons/react";
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
  type TrendVerdict,
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
import { REASON_ICON, STAGE_ICON } from "./icons";
import { Sparkline } from "./Sparkline";
import { Term } from "./Glossary";
import { Badge, Block, Collapsible, Empty, Figure, Panel, TEXT_TONE, Table, cell, hideNarrow, hideWide, numCell } from "./ui";

/* ---------- moedas ---------- */

export function DistanceBar({ pct }: { readonly pct: number | null }) {
  if (pct === null) return <span className="text-muted">—</span>;
  const width = (Math.min(Math.abs(pct), 60) / 60) * 100; // ±60% enche metade da barra
  const below = pct < 0;
  return (
    <span className="flex items-center justify-end gap-2">
      <span className="num">{fmt.pct(pct)}</span>
      <span aria-hidden className="relative block h-1.5 w-14 rounded-sm bg-ground">
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
    <span className={`flex items-center gap-1 ${pct >= 0 ? "text-good" : "text-muted"}`}>
      <Icon size={14} aria-hidden />
      {pct >= 0 ? "alta" : "baixa"}
    </span>
  );
}

export function MarketTable({ rows, sparks, recommended, selected, onSelect, maxHeight }: {
  readonly rows: readonly DailySignal[];
  readonly sparks: ReadonlyMap<string, readonly number[]>;
  readonly recommended: ReadonlySet<string>;
  readonly selected: string;
  readonly onSelect: (symbol: string) => void;
  readonly maxHeight?: string;
}) {
  return (
    <Table
      flush
      {...(maxHeight === undefined ? {} : { maxHeight })}
      caption="Todas as moedas monitoradas e a recomendação da regra de tendência para Bitcoin e Ethereum"
      columns={[
        { label: "Moeda" }, { label: "O que fazer" }, { label: "Preço", numeric: true },
        { label: "90 d", narrow: "hide" },
        { label: "Dist. média 200", numeric: true, narrow: "hide" }, { label: "Tendência", narrow: "wide" },
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
                <CoinLabel symbol={s.symbol} size={18} />
                {s.alert === "COMPRAR AGORA" && <Badge tone="signal">novo</Badge>}
                {s.alert === "VENDER AGORA" && <Badge tone="critical">saiu da alta</Badge>}
              </span>
            </td>
            <td className={cell} title={s.stage === "INDISPONÍVEL" ? s.stage_reason ?? undefined : undefined}>
              {s.stage === "INDISPONÍVEL" ? (
                <Badge tone={stage.tone}>{stage.text}</Badge>
              ) : !recommended.has(s.symbol) ? (
                <span className="text-muted">Só acompanhada</span>
              ) : s.stage === "NEUTRO" ? (
                <span className="text-muted">{stage.text}</span>
              ) : (
                <Badge tone={stage.tone}>
                  <span className="flex items-center gap-1">
                    {StageIcon !== null && <StageIcon size={12} aria-hidden />}
                    {stage.text}
                  </span>
                </Badge>
              )}
              {s.panic && <span className="ml-2 text-[12px] text-warning">em pânico</span>}
            </td>
            <td className={numCell}>{fmt.price(s.close)}</td>
            <td className={`${cell} ${hideNarrow}`}><Sparkline values={sparks.get(s.symbol) ?? []} label={`Preço de ${coinName(s.symbol)}`} /></td>
            <td className={`${numCell} ${hideNarrow}`}><DistanceBar pct={distance} /></td>
            <td className={`${cell} ${hideWide}`}><Trend pct={distance} /></td>
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
    <span className="flex items-center gap-1.5">
      <Icon size={14} className="text-muted" aria-hidden />
      {REASON_SHORT[reason]}
    </span>
  );
}

export function TradeList({ trades, coin, recommended, maxHeight }: {
  readonly trades: readonly Trade[];
  readonly coin: string;
  readonly recommended: boolean;
  readonly maxHeight?: string;
}) {
  if (!recommended) {
    return <Empty title={`Sem operações simuladas para ${coin}`}>A regra da média de 200 dias só dá sinal de compra para Bitcoin e Ethereum. A avaliação de {coin} para aporte está na aba Seleção.</Empty>;
  }
  if (trades.length === 0) {
    return <Empty title={`A regra nunca mandou comprar ${coin}`}>Desde o início dos dados.</Empty>;
  }
  return (
    <Table
      flush
      {...(maxHeight === undefined ? {} : { maxHeight })}
      caption={`Cada período em que a regra mandou comprar ou segurar ${coin}`}
      columns={[
        { label: "Entrada em" }, { label: "Preço", numeric: true, narrow: "hide" }, { label: "Venda simulada em" },
        { label: "Motivo" }, { label: "Resultado", numeric: true }, { label: "Dias", numeric: true, narrow: "hide" },
      ]}
    >
      {trades.toSorted((a, b) => b.entry_ts.getTime() - a.entry_ts.getTime()).map((t) => (
        <tr key={t.trade_id} className="border-b border-hairline">
          <td className={cell}>{fmt.day(t.entry_ts)}</td>
          <td className={`${numCell} ${hideNarrow}`}>{fmt.price(t.entry_price)}</td>
          <td className={cell}>{t.status === "ABERTA" ? <span className="text-muted">ainda aberta</span> : fmt.day(t.exit_ts)}</td>
          <td className={cell}><ReasonCell reason={t.exit_reason} /></td>
          <td className={`${numCell} ${TEXT_TONE[signTone(t.return_pct)]}`}>{fmt.pct(t.return_pct)}</td>
          <td className={`${numCell} ${hideNarrow}`}>{t.days_held ?? "—"}</td>
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
      flush
      caption={`Resultado da carteira no período ${label}, com taxa, spread e slippage em cada compra e venda`}
      columns={[
        { label }, { label: "Retorno total", numeric: true }, { label: "Por ano", numeric: true, narrow: "hide" },
        { label: "Pior queda", numeric: true }, { label: "Comprado", numeric: true, narrow: "hide" },
      ]}
    >
      {STRATEGY_ORDER.flatMap((strategy) => {
        const p = performanceOf(rows, universe, strategy, period);
        if (p === null) return [];
        return [
          <tr key={strategy} className="border-b border-hairline">
            <td className={`${cell} ${strategy === "TENDENCIA" ? "font-medium" : ""}`}>{STRATEGY_NAME[strategy]}</td>
            <td className={`${numCell} ${TEXT_TONE[signTone(p.total_return_pct)]}`}>{fmt.pct(p.total_return_pct, 0)}</td>
            <td className={`${numCell} ${hideNarrow} ${TEXT_TONE[signTone(p.annual_return_pct)]}`}>{fmt.pct(p.annual_return_pct)}</td>
            <td className={`${numCell} text-critical`}>{fmt.pct(p.max_drawdown_pct)}</td>
            <td className={`${numCell} ${hideNarrow}`}>{fmt.num(p.invested_pct, 0)}%</td>
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

/** A regra de tendência contra comprar e segurar: veredito, quedas, tabelas por período e operações por motivo. */
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
    <div className="grid gap-3 xl:grid-cols-12">
      <Panel id="bt-veredito" title="A regra de compra funciona?" className="xl:col-span-12">
        <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
          <div>
            <p className="flex items-start gap-2 text-[14px] font-semibold">
              <Scales size={20} weight="duotone" className={`mt-px shrink-0 ${verdict === "worse" ? "text-critical" : "text-good"}`} aria-hidden />
              <span>{verdict === null ? "Ainda não há dados suficientes para responder." : VERDICT_HEADLINE[verdict]}</span>
            </p>
            <Collapsible summary="Como foi feita a simulação" className="mt-1">
              Carteira com Bitcoin e Ethereum em partes iguais: o sinal é calculado no fechamento do dia e a compra ou venda acontece na abertura do dia seguinte, com taxa de 0,1%, spread e slippage estimados. A regra foi escolhida olhando só o
              período de treino; o período de teste são anos que a escolha não viu (mas já foram consultados em outras análises, então
              não são prospectivos). Comprar e segurar significa comprar no começo e nunca vender. A <Term id="drawdown">pior queda</Term>{" "}
              é o que importa para aguentar a <Term id="tendencia">tendência</Term> sem desistir.
            </Collapsible>
          </div>
          {trend !== null && hold !== null && (
            <div className="grid grid-cols-2 gap-6">
              <Figure label="Pior queda no teste: tendência" value={fmt.pct(trend.max_drawdown_pct, 0)} tone="critical" note={`Retorno de ${fmt.pct(trend.total_return_pct, 0)}`} />
              <Figure label="Pior queda no teste: comprar e segurar" value={fmt.pct(hold.max_drawdown_pct, 0)} tone="critical" note={`Retorno de ${fmt.pct(hold.total_return_pct, 0)}`} />
            </div>
          )}
        </div>
      </Panel>

      <Panel id="bt-principais" title="Bitcoin e Ethereum" note="o que as regras teriam rendido" className="xl:col-span-6" bodyClassName="space-y-3 p-3">
        <PerformanceTable rows={performance} universe="PRINCIPAIS" period="TREINO" />
        <PerformanceTable rows={performance} universe="PRINCIPAIS" period="TESTE" />
        <p className="text-[12px] text-muted">A regra antiga, comprar no pânico, perdeu dinheiro no treino e rendeu pouco no teste; por isso o pânico virou só um aviso.</p>
      </Panel>

      <Panel id="bt-todas" title="Todas as moedas analisadas" className="xl:col-span-6" bodyClassName="space-y-3 p-3">
        <PerformanceTable rows={performance} universe="TODAS" period="TREINO" />
        <PerformanceTable rows={performance} universe="TODAS" period="TESTE" />
        <p className="text-[12px] text-muted">
          Aplicada a todas as moedas, a regra reduz a queda, mas rende bem menos que comprar e segurar no teste; por isso o sinal de compra vale só para
          Bitcoin e Ethereum. As outras passam pela seleção (aba Seleção), que tem o próprio backtest.
        </p>
      </Panel>

      <Panel
        id="bt-operacoes"
        title="Como as compras de Bitcoin e Ethereum terminaram"
        note={`${all.count} compras simuladas, ${fmt.num(all.winRate, 0)}% com lucro, resultado médio ${fmt.pct(all.mean)}`}
        className="xl:col-span-12"
        bodyClassName="p-0"
      >
        <Table
          flush
          caption="Operações da regra de tendência agrupadas pelo motivo da venda"
          columns={[
            { label: "Motivo da venda" }, { label: "Operações", numeric: true }, { label: "Com lucro", numeric: true },
            { label: "Resultado médio", numeric: true }, { label: "Pior", numeric: true, narrow: "hide" }, { label: "Melhor", numeric: true, narrow: "hide" },
            { label: "Dias até vender", numeric: true, narrow: "hide" },
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
                <td className={`${numCell} ${hideNarrow} ${TEXT_TONE[signTone(x.worst)]}`}>{fmt.pct(x.worst)}</td>
                <td className={`${numCell} ${hideNarrow} ${TEXT_TONE[signTone(x.best)]}`}>{fmt.pct(x.best)}</td>
                <td className={`${numCell} ${hideNarrow}`}>{fmt.num(x.meanDays, 0)}</td>
              </tr>,
            ];
          })}
        </Table>
        <p className="border-t border-hairline px-3 py-2 text-[12px] text-muted">
          A regra erra muitas vezes com perdas pequenas e acerta algumas com ganhos enormes: é assim que seguir a tendência funciona. Limites: só
          moedas que existem hoje (as que sumiram não aparecem, o que favorece os resultados), uma única história de mercado, sem impostos e sem
          diferença entre a abertura do dia seguinte (uma aproximação) e o que se consegue pagar. O passado não garante o futuro.
        </p>
      </Panel>
    </div>
  );
}

/* ---------- como funciona ---------- */

export function HowItWorks() {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Block>
        <h3 className="flex items-center gap-2 font-medium"><HandCoins size={18} aria-hidden /> Quando comprar ou segurar</h3>
        <p className="mt-1 text-muted">Vale para Bitcoin e Ethereum. As duas coisas precisam acontecer ao mesmo tempo:</p>
        <ul className="mt-1 list-disc space-y-1 pl-5">
          <li>O preço da moeda fechou o dia acima da média dos últimos 200 dias. É o sinal de que ela está em tendência de alta.</li>
          <li>O Bitcoin também fechou acima da média dele. Quando o Bitcoin cai, quase tudo cai junto.</li>
        </ul>
        <p className="mt-2 text-muted">
          Enquanto as duas valem, quem não tem pode comprar e quem já tem deve segurar.{" "}
          <strong className="font-medium text-ink">Ficar de olho</strong> é a etapa anterior: o preço está até 3% abaixo
          da média de 200 dias e subindo, perto de cruzá-la.
        </p>
        <p className="mt-2 text-muted">
          Nas outras moedas esta regra não dá sinal de compra (o teste mostrou que ela não compensa nelas); elas são
          avaliadas pela seleção, que exige também momento, liquidez e risco dentro dos limites.
          O <strong className="font-medium text-ink">pânico</strong> (queda forte com medo no mercado) aparece só como aviso.
          Comprar nele perdeu dinheiro.
        </p>
      </Block>
      <Block>
        <h3 className="font-medium">Quando vender o que você comprou</h3>
        <p className="mt-1 text-muted">A primeira regra que acontecer manda vender:</p>
        <ul className="mt-2 space-y-2">
          {SELL_ORDER.map((r) => {
            const Icon = REASON_ICON[r];
            return (
              <li key={r} className="flex gap-2">
                <Icon size={18} className="mt-0.5 shrink-0 text-muted" aria-hidden />
                <span><strong className="font-medium">{REASON_SHORT[r]}:</strong> {RULE_TEXT[r]}.</span>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-muted">
          O pipeline atualiza tudo uma vez por dia, depois que o dia fecha (21h no horário de Brasília). Isto é uma
          ferramenta estatística, não recomendação de investimento.
        </p>
      </Block>
    </div>
  );
}

const SELL_ORDER: readonly ExitReason[] = ["TENDENCIA", "MERCADO", "STOP"];
