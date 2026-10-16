import { useState } from "react";
import { coinName, fmt, horizonName, modelForecast } from "../data/analytics";
import { coinFullName } from "../data/coins";
import type { Forecast, HistoryPoint, Position, Trade } from "../types/signals";
import { CoinLogo } from "./CoinLabel";
import { Term } from "./Glossary";
import { PriceChart } from "./PriceChart";
import { Badge, Collapsible, Empty, Panel, Table, cell, hideNarrow, hideWide, numCell } from "./ui";

const METHOD_NAME: Readonly<Record<string, string>> = {
  PASSEIO_ALEATORIO: "Preço de hoje com ruído",
  BOOTSTRAP_BLOCOS: "Reamostragem de blocos",
  EWMA: "Volatilidade que reage rápido",
};

const pctOf = (x: number): string => `${fmt.num(x * 100, 0)}%`;

function EvaluationTable({ rows }: { readonly rows: readonly Forecast[] }) {
  return (
    <Table
      flush
      caption="Previsão de hoje e avaliação no período de teste, ao lado do preço de hoje como referência"
      columns={[
        { label: "Horizonte" },
        { label: "Faixa P10 a P90", numeric: true },
        { label: "Meio (P50)", numeric: true, narrow: "wide" },
        { label: "Volatilidade", numeric: true, narrow: "wide" },
        { label: "Erro médio: modelo / hoje", numeric: true },
        { label: "Acerto da direção", numeric: true, narrow: "wide" },
        { label: "Cobertura (meta 80%)", numeric: true, narrow: "hide" },
        { label: "Método", narrow: "wide" },
        { label: "Resultado" },
      ]}
    >
      {rows.map((f) => (
        <tr key={f.horizon_days} className="border-t border-hairline">
          <td className={cell}>{horizonName(f.horizon_days)}</td>
          <td className={numCell}>{fmt.pct(f.p10_pct)} a {fmt.pct(f.p90_pct)}</td>
          <td className={`${numCell} ${hideWide}`}>{fmt.pct(f.p50_pct)}</td>
          <td className={`${numCell} ${hideWide}`}>{fmt.num(f.vol_pct)}%</td>
          <td className={numCell}>{fmt.num(f.mae_pct)} / {fmt.num(f.base_mae_pct)}</td>
          <td className={`${numCell} ${hideWide}`}>{pctOf(f.directional_acc)} / {pctOf(f.base_directional_acc)}</td>
          <td className={`${numCell} ${hideNarrow}`}>
            <span className={f.coverage_ok ? "" : "text-warning"}>{pctOf(f.coverage)}</span> / {pctOf(f.base_coverage)}
          </td>
          <td className={`${cell} ${hideWide}`}>
            {METHOD_NAME[f.method] ?? f.method}
            <span className="block text-[11px] text-muted">{f.params}</span>
          </td>
          <td className={cell}>
            {f.beats_baseline ? <Badge tone="good">Vence o preço de hoje</Badge> : <Badge tone="warning">Sem vantagem</Badge>}
          </td>
        </tr>
      ))}
    </Table>
  );
}

function SymbolForecast({ symbol, rows, history, trades, positions }: {
  readonly symbol: string;
  readonly rows: readonly Forecast[];
  readonly history: readonly HistoryPoint[];
  readonly trades: readonly Trade[];
  readonly positions: readonly Position[];
}) {
  const [show, setShow] = useState(true);
  const first = rows[0];
  const long = rows.find((r) => r.horizon_days === 30);
  return (
    <Panel
      id={`prev-${coinName(symbol)}`}
      title={<span className="flex items-center gap-2"><CoinLogo symbol={symbol} size={18} />{coinFullName(symbol)}</span>}
      actions={
        first === undefined ? undefined : (
          <label className="flex items-center gap-1.5 text-[12px]">
            <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
            Faixa de previsão
          </label>
        )
      }
      bodyClassName="p-0"
    >
      {first === undefined ? (
        <div className="p-3"><Empty title="Sem previsão para esta moeda hoje">Os dados estão desatualizados ou insuficientes.</Empty></div>
      ) : (
        <>
          <div className="p-3">
            <PriceChart history={history} trades={trades} positions={positions} forecast={rows} showForecast={show} height={260} />
          </div>
          <EvaluationTable rows={rows} />
          <p className="border-t border-hairline px-3 py-2 text-[12px] text-muted">
            Teste de {fmt.day(first.test_start)} a {fmt.day(first.test_end)}, sem dados do futuro e com parâmetros escolhidos antes. Em 1 dia são{" "}
            {first.n_eval.toLocaleString("pt-BR")} janelas; em 30 dias, {long === undefined ? "poucas" : `só ${long.n_eval}`}, então a evidência de longo prazo é fraca.
          </p>
        </>
      )}
    </Panel>
  );
}

export function ForecastView({ forecast, symbols, history, trades, positions }: {
  readonly forecast: readonly Forecast[];
  readonly symbols: readonly string[];
  readonly history: readonly HistoryPoint[];
  readonly trades: readonly Trade[];
  readonly positions: readonly Position[];
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-hairline bg-surface px-3 py-2">
        <Collapsible summary="Como ler a previsão (e quais são os limites)">
          <ul className="list-disc space-y-1 pl-5">
            <li>
              A <Term id="faixa">faixa de previsão</Term> mostra onde o retorno deve ficar em 8 de cada 10 vezes. É uma medida de incerteza, não um palpite de direção.
            </li>
            <li>
              Cada modelo é comparado com <Term id="baseline">o preço de hoje</Term>. Se não vence essa referência no teste, o painel diz que não há vantagem demonstrada.
            </li>
            <li>
              A <Term id="volatilidade">volatilidade</Term> alta deixa a faixa larga. A cobertura mede se os 80% prometidos se cumpriram no teste.
            </li>
            <li>Limites: poucas janelas independentes em 30 dias, só moedas que sobreviveram, uma única história de mercado e sem impostos.</li>
          </ul>
        </Collapsible>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        {symbols.map((symbol) => (
          <SymbolForecast
            key={symbol}
            symbol={symbol}
            rows={modelForecast(forecast, symbol)}
            history={history.filter((h) => h.symbol === symbol)}
            trades={trades.filter((t) => t.symbol === symbol)}
            positions={positions.filter((p) => p.symbol === symbol)}
          />
        ))}
      </div>
    </div>
  );
}
