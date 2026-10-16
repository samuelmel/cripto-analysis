import { useState } from "react";
import { coinName, fmt, type SignalView, type Verdict } from "../data/analytics";
import { RECOMMENDED_SYMBOLS, coinFullName } from "../data/coins";
import type { ClosedPosition, DailySignal, Forecast, HistoryPoint, Position, Recommendation, Trade } from "../types/signals";
import { CoinLogo } from "./CoinLabel";
import { CoreTable, ForecastMini } from "./Overview";
import { PositionsSection } from "./Positions";
import { PriceChart } from "./PriceChart";
import { DiscardedTable, RecommendationPanel } from "./Recommendation";
import { MarketTable, VerdictLine } from "./Sections";
import { Empty, Panel, Segmented } from "./ui";

type SideTab = "posicoes" | "previsao" | "descartadas";
const SIDE_TABS: Readonly<Record<SideTab, string>> = { posicoes: "Posições", previsao: "Previsão", descartadas: "Descartadas" };

interface CoreRow {
  readonly signal: DailySignal;
  readonly view: SignalView;
  readonly change1: number | null;
  readonly change30: number | null;
  readonly closes: readonly number[];
}

/**
 * Visão geral em duas colunas no desktop: à esquerda o gráfico e a tabela de moedas; à direita a recomendação, a regra
 * principal e um painel de apoio com abas (posições, previsão, descartadas). Cada coluna cabe na primeira tela.
 */
export function OverviewView(props: {
  readonly signals: readonly DailySignal[];
  readonly recommendation: Recommendation;
  readonly verdict: Verdict;
  readonly asOf: string;
  readonly coreRows: readonly CoreRow[];
  readonly selected: string;
  readonly onSelect: (symbol: string) => void;
  readonly coinsByName: readonly DailySignal[];
  readonly sparks: ReadonlyMap<string, readonly number[]>;
  readonly chartHistory: readonly HistoryPoint[];
  readonly chartTrades: readonly Trade[];
  readonly chartPositions: readonly Position[];
  readonly chartForecast: readonly Forecast[];
  readonly forecast: readonly Forecast[];
  readonly positions: readonly Position[];
  readonly closed: readonly ClosedPosition[];
  readonly onDetails: () => void;
  readonly onChanged: () => Promise<void>;
}) {
  const [showForecast, setShowForecast] = useState(true);
  const [side, setSide] = useState<SideTab>("posicoes");
  const { selected, signals } = props;
  const core = [...RECOMMENDED_SYMBOLS];

  return (
    <div className="grid items-start gap-3 lg:grid-cols-12">
      <div className="min-w-0 space-y-3 lg:col-span-7 xl:col-span-8">
        <Panel
          id="grafico"
          title={
            <span className="flex items-center gap-2">
              <CoinLogo symbol={selected} size={18} />
              {coinFullName(selected)} ({coinName(selected)})
              <span className="font-normal text-muted">desde {fmt.day(props.chartHistory[0]?.timestamp ?? null)}</span>
            </span>
          }
          actions={
            <>
              {props.chartForecast.length > 0 && (
                <label className="flex items-center gap-1.5 text-[12px]">
                  <input type="checkbox" checked={showForecast} onChange={(e) => setShowForecast(e.target.checked)} />
                  Faixa de previsão (estimativa)
                </label>
              )}
              <select
                aria-label="Moeda do gráfico"
                value={selected}
                onChange={(e) => props.onSelect(e.target.value)}
                className="rounded-sm border border-hairline bg-surface px-2 py-0.5 text-[12px]"
              >
                {props.coinsByName.map((s) => <option key={s.symbol} value={s.symbol}>{coinName(s.symbol)}</option>)}
              </select>
            </>
          }
        >
          {props.chartHistory.length === 0 ? (
            <Empty title="Sem histórico de preço para esta moeda">O gráfico precisa do history.parquet do pipeline.</Empty>
          ) : (
            <PriceChart
              history={props.chartHistory}
              trades={props.chartTrades}
              positions={props.chartPositions}
              forecast={props.chartForecast}
              showForecast={showForecast}
              height={300}
            />
          )}
        </Panel>
        <Panel id="moedas" title="Moedas monitoradas" note="clique para ver o gráfico" bodyClassName="p-0">
          <MarketTable
            rows={signals}
            recommended={RECOMMENDED_SYMBOLS}
            sparks={props.sparks}
            selected={selected}
            onSelect={props.onSelect}
            maxHeight="max-h-[300px]"
          />
        </Panel>
      </div>

      <div className="min-w-0 space-y-3 lg:col-span-5 xl:col-span-4">
        <RecommendationPanel signals={signals} rec={props.recommendation} onDetails={props.onDetails} />
        <Panel id="regra" title="Regra principal: média de 200 dias" note="Bitcoin e Ethereum" bodyClassName="space-y-2 p-3">
          <VerdictLine verdict={props.verdict} asOf={props.asOf} />
          <CoreTable rows={props.coreRows} selected={selected} onSelect={props.onSelect} />
        </Panel>
        <Panel
          id="apoio"
          title={SIDE_TABS[side]}
          actions={<Segmented label="Painel de apoio" value={side} options={SIDE_TABS} onChange={setSide} />}
          bodyClassName="scroll-thin max-h-[340px] overflow-auto p-3"
        >
          {side === "posicoes" && (
            <PositionsSection positions={props.positions} closed={props.closed} coins={props.coinsByName} onChanged={props.onChanged} />
          )}
          {side === "previsao" &&
            (props.forecast.length === 0 ? (
              <Empty title="Ainda não há previsão para mostrar">Rode o pipeline para gerar a previsão.</Empty>
            ) : (
              <ForecastMini forecast={props.forecast} symbols={core} />
            ))}
          {side === "descartadas" && (
            <>
              <p className="mb-2 text-[12px] text-muted">
                {props.recommendation.n_analyzed} moedas analisadas, {props.recommendation.n_candidates} com sinais favoráveis,{" "}
                {props.recommendation.n_funded} com aporte.
              </p>
              <DiscardedTable signals={signals} />
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
