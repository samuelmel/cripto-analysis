import { useState } from "react";
import { coinName, fmt, horizonName, modelForecast } from "../data/analytics";
import { coinFullName } from "../data/coins";
import type { Forecast, HistoryPoint, Position, Trade } from "../types/signals";
import { CoinLogo } from "./CoinLabel";
import { Term } from "./Glossary";
import { PriceChart } from "./PriceChart";
import { Badge, Block, Table, cell, hideNarrow, numCell } from "./ui";

const METHOD_NAME: Readonly<Record<string, string>> = {
  PASSEIO_ALEATORIO: "Preço de hoje com ruído",
  BOOTSTRAP_BLOCOS: "Reamostragem de blocos",
  EWMA: "Volatilidade que reage rápido",
};

const pctOf = (x: number): string => `${fmt.num(x * 100, 0)}%`;

function EvaluationTable({ rows }: { readonly rows: readonly Forecast[] }) {
  return (
    <Table
      caption="Previsão de hoje e avaliação no período de teste, ao lado do preço de hoje como referência"
      columns={[
        { label: "Horizonte" },
        { label: "Faixa P10 a P90", numeric: true },
        { label: "Meio (P50)", numeric: true, narrow: "hide" },
        { label: "Volatilidade", numeric: true, narrow: "hide" },
        { label: "Erro médio: modelo / preço de hoje", numeric: true },
        { label: "Acerto da direção", numeric: true, narrow: "hide" },
        { label: "Cobertura da faixa (meta 80%)", numeric: true, narrow: "hide" },
        { label: "Método", narrow: "hide" },
        { label: "Resultado" },
      ]}
    >
      {rows.map((f) => (
        <tr key={f.horizon_days} className="border-b border-hairline align-top">
          <td className={cell}>{horizonName(f.horizon_days)}</td>
          <td className={numCell}>{fmt.pct(f.p10_pct)} a {fmt.pct(f.p90_pct)}</td>
          <td className={`${numCell} ${hideNarrow}`}>{fmt.pct(f.p50_pct)}</td>
          <td className={`${numCell} ${hideNarrow}`}>{fmt.num(f.vol_pct)}%</td>
          <td className={numCell}>{fmt.num(f.mae_pct)} / {fmt.num(f.base_mae_pct)}</td>
          <td className={`${numCell} ${hideNarrow}`}>{pctOf(f.directional_acc)} / {pctOf(f.base_directional_acc)}</td>
          <td className={`${numCell} ${hideNarrow}`}>
            <span className={f.coverage_ok ? "" : "text-warning"}>{pctOf(f.coverage)}</span> / {pctOf(f.base_coverage)}
          </td>
          <td className={`${cell} ${hideNarrow}`}>
            {METHOD_NAME[f.method] ?? f.method}
            <span className="block text-[13px] text-muted">{f.params}</span>
          </td>
          <td className={cell}>
            {f.beats_baseline ? <Badge tone="good">Vence o preço de hoje</Badge> : <Badge tone="warning">Sem vantagem demonstrada</Badge>}
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
    <section aria-labelledby={`prev-${coinName(symbol)}`} className="mt-10 first:mt-0">
      <h3 id={`prev-${coinName(symbol)}`} className="flex items-center gap-3 text-lg font-semibold">
        <CoinLogo symbol={symbol} size={28} />
        {coinFullName(symbol)}
      </h3>
      {first === undefined ? (
        <p className="mt-3 text-muted">Sem previsão para esta moeda hoje: os dados estão desatualizados ou insuficientes.</p>
      ) : (
        <>
          <div className="mt-4">
            <Block>
              <label className="mb-3 flex items-center gap-2 text-[14px]">
                <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
                Mostrar a faixa de previsão no gráfico
              </label>
              <PriceChart history={history} trades={trades} positions={positions} forecast={rows} showForecast={show} />
            </Block>
          </div>
          <div className="mt-5">
            <EvaluationTable rows={rows} />
          </div>
          <p className="mt-3 max-w-[72ch] text-[13px] text-muted">
            Teste de {fmt.day(first.test_start)} a {fmt.day(first.test_end)}, sem dados do futuro e com parâmetros escolhidos antes.
            Em 1 dia são {first.n_eval.toLocaleString("pt-BR")} janelas; em 30 dias, {long === undefined ? "poucas" : `só ${long.n_eval}`}, então a evidência de longo prazo é fraca.
          </p>
        </>
      )}
    </section>
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
    <>
      <Block>
        <h2 className="text-lg font-semibold">Como ler a previsão</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5">
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
      </Block>
      <div className="mt-8">
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
    </>
  );
}
