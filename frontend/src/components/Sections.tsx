import {
  REASON_SHORT,
  REASON_TEXT,
  RULE_TEXT,
  STAGE_LABEL,
  byReason,
  coinName,
  distanceFromAverage,
  fmt,
  momentumLabel,
  signTone,
  signalHasEdge,
  summarize,
  type Tone,
  type Verdict,
} from "../data/analytics";
import { EXIT_REASONS, type DailySignal, type Position, type Trade } from "../types/signals";
import { Badge, Block, Figure, TEXT_TONE, Table, cell, numCell } from "./ui";

/* ---------- hoje ---------- */

const VERDICT_BORDER = {
  good: "border-good-mark",
  critical: "border-critical-mark",
  warning: "border-warning-mark",
  neutral: "border-hairline",
  signal: "border-signal",
} as const;

export function TodayPanel({ verdict, fng, fngText, fngTone, asOf }: {
  readonly verdict: Verdict;
  readonly fng: number | null;
  readonly fngText: string;
  readonly fngTone: Tone;
  readonly asOf: string;
}) {
  return (
    <div className="grid gap-6 md:grid-cols-[1fr_auto]">
      <div className={`rounded-md border-2 bg-surface p-6 ${VERDICT_BORDER[verdict.tone]}`}>
        <p className="text-[13px] text-muted">Hoje, com o fechamento de {asOf}</p>
        <p className="mt-2 text-[28px] font-semibold leading-tight tracking-[-0.01em]">{verdict.headline}</p>
        <ul className="mt-3 space-y-1">
          {verdict.details.map((d) => <li key={d}>{d}</li>)}
        </ul>
      </div>
      <Block className="md:w-64">
        <Figure
          label="Humor do mercado (Fear & Greed)"
          value={fng === null ? "—" : `${fng}`}
          tone={fngTone}
          note={`${fngText} — de 0 (pânico) a 100 (euforia)`}
        />
      </Block>
    </div>
  );
}

/* ---------- posições ---------- */

export function PositionsTable({ positions }: { readonly positions: readonly Position[] }) {
  if (positions.length === 0) {
    return (
      <Block>
        <p>Você ainda não registrou nenhuma compra.</p>
        <p className="mt-2 text-muted">
          Quando comprar, registre no terminal, na pasta do projeto. Exemplo para 0,01 BTC a US$ 83.000:
        </p>
        <pre className="mt-3 overflow-x-auto rounded-sm bg-ground px-3 py-2 text-[13px]">uv run python -m src.positions add BTC/USDT 83000 0.01</pre>
      </Block>
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {positions.map((p) => <PositionCard key={p.position_id} p={p} />)}
    </div>
  );
}

function Fact({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="flex justify-between gap-4 border-t border-hairline py-2 text-[14px]">
      <dt className="text-muted">{label}</dt>
      <dd className="num whitespace-nowrap text-right">{value}</dd>
    </div>
  );
}

function PositionCard({ p }: { readonly p: Position }) {
  const sell = p.action === "VENDER";
  return (
    <article className="rounded-md border border-hairline bg-surface p-6" aria-label={`Posição em ${coinName(p.symbol)}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold">{coinName(p.symbol)}</h3>
          <p className="text-[13px] text-muted">{fmt.num(p.qty, 4)} comprados em {fmt.day(p.entry_ts)}</p>
        </div>
        {sell ? <Badge tone="critical">Vender</Badge> : <Badge tone="good">Segurar</Badge>}
      </div>
      <p className={`mt-4 text-[32px] font-medium leading-tight ${TEXT_TONE[signTone(p.return_pct)]}`}>
        {fmt.pct(p.return_pct)} <span className="text-lg">{fmt.usd(p.pnl_usd)}</span>
      </p>
      <p className="mt-2 text-muted">
        {sell && p.reason !== null
          ? `${REASON_TEXT[p.reason].replace(/^./, (c) => c.toUpperCase())} (desde ${fmt.day(p.signal_ts)}).`
          : "Nenhuma regra de venda disparou. Pode continuar com ela."}
      </p>
      <dl className="mt-4">
        <Fact label="Você pagou" value={fmt.price(p.entry_price)} />
        <Fact label="Preço hoje" value={fmt.price(p.last_close)} />
        <Fact label="Limite de perda: vender se cair a" value={fmt.price(p.stop_price)} />
        <Fact
          label="Garantir lucro: vender se cair a"
          value={p.trail_price === null ? "ativa depois de subir 15%" : fmt.price(p.trail_price)}
        />
        <Fact label="Preço médio de 90 dias" value={fmt.price(p.target_price)} />
      </dl>
    </article>
  );
}

/* ---------- moedas ---------- */

function DistanceBar({ pct }: { readonly pct: number | null }) {
  if (pct === null) return <span className="text-muted">—</span>;
  const width = (Math.min(Math.abs(pct), 30) / 30) * 100; // ±30% enche metade da barra
  const below = pct < 0;
  return (
    <span className="flex items-center justify-end gap-3">
      <span className="num">{fmt.pct(pct)}</span>
      <span aria-hidden className="relative block h-2 w-28 rounded-sm bg-ground">
        <span className="absolute inset-y-0 left-1/2 w-px bg-hairline" />
        <span
          className={`absolute inset-y-0 rounded-sm ${below ? "right-1/2 bg-critical-mark" : "left-1/2 bg-series-price"}`}
          style={{ width: `${width / 2}%` }}
        />
      </span>
    </span>
  );
}

export function MarketTable({ rows, selected, onSelect }: {
  readonly rows: readonly DailySignal[];
  readonly selected: string;
  readonly onSelect: (symbol: string) => void;
}) {
  return (
    <Table
      caption="Todas as moedas monitoradas, da mais abaixo do normal para a mais acima"
      columns={[
        { label: "Moeda" }, { label: "Situação" }, { label: "Preço", numeric: true },
        { label: "Distância da média de 90 dias", numeric: true }, { label: "Ritmo dos últimos 14 dias" },
      ]}
    >
      {rows.map((s) => {
        const stage = STAGE_LABEL[s.stage];
        const momentum = momentumLabel(s.rsi_14);
        const isSelected = s.symbol === selected;
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
            <td className={`${cell} font-medium`}>
              {coinName(s.symbol)}
              {s.alert === "COMPRAR AGORA" && <span className="ml-2"><Badge tone="signal">novo hoje</Badge></span>}
            </td>
            <td className={cell}>{s.stage === "NEUTRO" ? <span className="text-muted">{stage.text}</span> : <Badge tone={stage.tone}>{stage.text}</Badge>}</td>
            <td className={numCell}>{fmt.price(s.close)}</td>
            <td className={numCell}><DistanceBar pct={distanceFromAverage(s.close, s.sma_90)} /></td>
            <td className={`${cell} ${momentum.tone === "warning" ? "text-warning" : "text-muted"}`}>{momentum.text}</td>
          </tr>
        );
      })}
    </Table>
  );
}

/* ---------- histórico de uma moeda ---------- */

export function TradeList({ trades, coin }: { readonly trades: readonly Trade[]; readonly coin: string }) {
  if (trades.length === 0) {
    return <p className="text-muted">O sinal de compra nunca disparou para {coin} desde o início dos dados.</p>;
  }
  return (
    <Table
      caption={`Cada vez que o sinal de compra disparou para ${coin}`}
      columns={[
        { label: "Sinal em" }, { label: "Preço", numeric: true }, { label: "Venda simulada em" },
        { label: "Motivo" }, { label: "Resultado", numeric: true }, { label: "Dias", numeric: true },
      ]}
    >
      {trades.toSorted((a, b) => b.entry_ts.getTime() - a.entry_ts.getTime()).map((t) => (
        <tr key={t.trade_id} className="border-b border-hairline">
          <td className={cell}>{fmt.day(t.entry_ts)}</td>
          <td className={numCell}>{fmt.price(t.entry_price)}</td>
          <td className={cell}>{t.status === "ABERTA" ? <span className="text-muted">ainda aberta</span> : fmt.day(t.exit_ts)}</td>
          <td className={cell}>{t.exit_reason === null ? "—" : REASON_SHORT[t.exit_reason]}</td>
          <td className={`${numCell} ${TEXT_TONE[signTone(t.return_pct)]}`}>{fmt.pct(t.return_pct)}</td>
          <td className={numCell}>{t.days_held ?? "—"}</td>
        </tr>
      ))}
    </Table>
  );
}

/* ---------- a regra funciona? ---------- */

export function BacktestPanel({ signal, reference, since }: {
  readonly signal: readonly Trade[];
  readonly reference: readonly Trade[];
  readonly since: string;
}) {
  const s = summarize(signal);
  const r = summarize(reference);
  const edge = signalHasEdge(s, r);
  const reasons = byReason(signal);
  return (
    <>
      <Block>
        <p className="text-lg font-semibold">
          {edge === false && "Não. No passado, comprar no sinal rendeu menos do que comprar num dia qualquer."}
          {edge === true && "Sim. No passado, comprar no sinal rendeu mais do que comprar num dia qualquer."}
          {edge === null && "Ainda não há operações suficientes para responder."}
        </p>
        <p className="mt-2 max-w-[72ch] text-muted">
          Simulamos cada vez que o sinal disparou desde {since}, vendendo pelas mesmas regras usadas nas suas posições.
          Para comparar, simulamos também comprar toda semana, sem critério nenhum, com as mesmas regras de venda.
          {edge === false && " O pânico extremo costuma continuar por semanas, e o sinal compra cedo demais. Use-o como alerta para prestar atenção, não como ordem de compra."}
        </p>
        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          <div className="border-t border-hairline pt-4">
            <p className="font-medium">Comprando no sinal</p>
            <div className="mt-3 grid grid-cols-2 gap-4">
              <Figure label="Resultado médio por operação" value={fmt.pct(s.mean)} tone={signTone(s.mean)} />
              <Figure label="Operações com lucro" value={`${fmt.num(s.winRate, 0)}%`} note={`de ${s.count} operações`} />
            </div>
          </div>
          <div className="border-t border-hairline pt-4">
            <p className="font-medium">Comprando toda semana, sem critério</p>
            <div className="mt-3 grid grid-cols-2 gap-4">
              <Figure label="Resultado médio por operação" value={fmt.pct(r.mean)} tone={signTone(r.mean)} />
              <Figure label="Operações com lucro" value={`${fmt.num(r.winRate, 0)}%`} note={`de ${r.count.toLocaleString("pt-BR")} operações`} />
            </div>
          </div>
        </div>
      </Block>

      <h3 className="mt-8 font-medium">Como as compras do sinal terminaram</h3>
      <div className="mt-3">
        <Table
          caption="Operações do sinal de compra agrupadas pelo motivo da venda"
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
                <td className={cell}>{REASON_SHORT[reason]}</td>
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
    </>
  );
}

/* ---------- como funciona ---------- */

export function HowItWorks() {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Block>
        <h3 className="font-medium">Quando uma moeda entra na zona de compra</h3>
        <p className="mt-2 text-muted">As três coisas precisam acontecer ao mesmo tempo:</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>O preço caiu muito abaixo do normal dos últimos 90 dias (mais de 2,5 vezes a variação típica).</li>
          <li>A queda foi rápida: o indicador RSI, que mede o ritmo dos últimos 14 dias, está abaixo de 30.</li>
          <li>O mercado inteiro está em pânico: o Fear & Greed está abaixo de 25.</li>
        </ul>
        <p className="mt-3 text-muted">
          <strong className="font-medium text-ink">Ficar de olho</strong> é a etapa anterior: a moeda está caindo nessa
          direção (abaixo de 1,5 vez a variação típica e RSI abaixo de 40), mas ainda não chegou lá.
        </p>
      </Block>
      <Block>
        <h3 className="font-medium">Quando vender o que você comprou</h3>
        <p className="mt-2 text-muted">A primeira regra que acontecer manda vender:</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {EXIT_REASONS.map((r) => (
            <li key={r}><strong className="font-medium">{REASON_SHORT[r]}:</strong> {RULE_TEXT[r]}.</li>
          ))}
        </ul>
        <p className="mt-3 text-muted">
          O pipeline atualiza tudo uma vez por dia, depois que o dia fecha (21h no horário de Brasília). Isto é uma
          ferramenta estatística, não recomendação de investimento.
        </p>
      </Block>
    </div>
  );
}
