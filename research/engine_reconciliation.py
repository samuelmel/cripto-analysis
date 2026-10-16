"""Reconciliação dos motores: do resultado antigo ao novo, uma premissa por vez.

Uso (da raiz do projeto):

    uv run python research/engine_reconciliation.py              base do pipeline (data/market)
    uv run python research/engine_reconciliation.py --archive    as moedas de config.UNIVERSE na base do arquivo
                                                                 oficial da Binance (data/archive), sem Fear & Greed

Para cada estratégia e período, a tabela mostra o retorno total:
    LEGADO            motor antigo (`run_portfolio` ou `run_weighted`), como era publicado antes da Fase 2
    1_mesmas_premissas  motor único com as premissas do legado: universo = ter SMA 200; começa cada período em
                      caixa e só usa decisões de dentro do período; carteira com só taxa e rebalanceamento diário;
                      seleção com os mesmos custos e banda
    2_posicao_inicial + começa o período com a última decisão conhecida ANTES dele (executada na 1ª abertura)
    3_custos          + meio-spread e slippage do `costs.py` (só carteira; a seleção já os tinha)
    4_universo_pit    + universo point-in-time (= resultado PUBLICADO pelo pipeline novo)
Sensibilidade (não entra no resultado publicado):
    sens_banda_5pp          carteira com banda de 5 pontos (config.REBALANCE_BAND) em vez do rebalanceamento diário
    sens_deslistagem_100    deslistagem com recuperação de 100% do último preço em vez de 0% (config.DELIST_RECOVERY)
Em todos os passos a ordem decidida no fechamento de D é executada na abertura de D+1. A diferença entre LEGADO e
1_mesmas_premissas junta o efeito de executar na abertura seguinte, o tratamento de candle ausente, a baixa de
ativo que parou de negociar e o fim da alavancagem implícita do legado; as demais colunas isolam uma premissa cada.

Grava data/research/engine_reconciliation.parquet. Resultados com dados reais são EXPLORATÓRIOS: o período de
teste (2023 em diante) já foi consultado no desenvolvimento e o universo de candidatas é a lista de hoje.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (  # noqa: E402
    BUDGET_BRL,
    FEE_PER_SIDE,
    RECOMMENDED,
    REBALANCE_BAND,
    SELECTION_REBALANCE_DAYS,
    UNIVERSE,
)
from src.loaders.archive_store import read_archive_candles  # noqa: E402
from src.loaders.market_store import read_fng, read_ohlcv  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.pipeline import PERIODS, SELECTION_PERIODS, backtest_inputs  # noqa: E402
from src.transformers.anomaly_detector import classify_history  # noqa: E402
from src.transformers.backtest_engine import ExecutionConfig, run_backtest, summarize  # noqa: E402
from src.transformers.costs import CostModel  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.portfolio_backtest import (  # noqa: E402
    checked,
    equal_weight,
    investable_mask,
    select_panel,
    strategy_signals,
)
from src.transformers.selection import compute_features, regime_series  # noqa: E402
from src.transformers.selection_backtest import (  # noqa: E402
    _all_targets,
    evaluate_selection_legacy,
)
from src.transformers.strategies import market_from_candles  # noqa: E402
from src.transformers.trade_simulator import evaluate_portfolio, wide  # noqa: E402
from src.transformers.universe import select_universe  # noqa: E402
from src.transformers.selection import SelectionRules  # noqa: E402
from src.transformers.allocation import AllocationRules  # noqa: E402

OUT = Path("data/research/engine_reconciliation.parquet")


def _inside(targets: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    """Só as decisões de dentro do período (como o legado): sem posição herdada de antes do início."""
    return targets.loc[targets.index >= start]


def _total(result: object) -> float:
    from src.transformers.backtest_engine import BacktestResult

    assert isinstance(result, BacktestResult)
    return float(summarize(checked(result, "reconciliação"))["total"])


def reconcile_engines(raw: pd.DataFrame, fng: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (seção, universo, estratégia, período) com o retorno total de cada passo."""
    kept = select_universe(UNIVERSE, raw).kept
    candles = clean_candles(raw[raw["symbol"].isin(kept)])
    history = classify_history(candles, fng)
    bt = backtest_inputs(raw, fng)
    model = bt.cfg.costs
    fee_only = ExecutionConfig(costs=CostModel(fee_rate=model.fee_rate, slippage=0.0, spread_tiers=((0.0, 0.0),)))
    full_daily = ExecutionConfig(costs=model)
    full_band = ExecutionConfig(costs=model, rebalance_band=REBALANCE_BAND)
    daily_recover = ExecutionConfig(costs=model, delist_recovery=1.0)
    band_recover = ExecutionConfig(costs=model, rebalance_band=REBALANCE_BAND, delist_recovery=1.0)
    rows: list[dict[str, object]] = []

    # ---- carteira (performance.parquet): motor legado run_portfolio ---------------------------------------
    closes = wide(history, "close")
    returns = closes.pct_change(fill_method=None)
    valid = wide(history, "sma_200").notna()
    legacy_signals = strategy_signals(history)
    new_signals = strategy_signals(bt.history)
    pit_investable = investable_mask(bt.history, bt.eligible)
    for universe, legacy_cols, new_cols in (
        ("PRINCIPAIS", list(RECOMMENDED), list(RECOMMENDED)),
        ("TODAS", list(kept), list(bt.symbols)),
    ):
        lc = [c for c in legacy_cols if c in closes.columns]
        nc = [c for c in new_cols if c in pit_investable.columns]
        for strategy in legacy_signals:
            if strategy == "PANICO" and fng.empty:
                continue  # sem Fear & Greed o pânico nunca dispara: comparação sem sentido
            legacy_targets = equal_weight(legacy_signals[strategy][lc], valid[lc])
            pit_targets = equal_weight(new_signals[strategy][nc], pit_investable[nc])
            for period, (start, end) in PERIODS.items():
                legacy = evaluate_portfolio(legacy_signals[strategy][lc].reindex_like(closes[lc]).fillna(0.0),
                                            returns[lc], valid[lc], start, end, FEE_PER_SIDE)
                sub = select_panel(bt.panel, lc)
                rows.append({
                    "section": "carteira", "universe": universe, "strategy": strategy, "period": period,
                    "LEGADO": float(legacy["total"]),
                    "1_mesmas_premissas": _total(run_backtest(sub, _inside(legacy_targets, start), eligible=valid[lc],
                                                              cfg=fee_only, start=start, end=end)),
                    "2_posicao_inicial": _total(run_backtest(sub, legacy_targets, eligible=valid[lc], cfg=fee_only, start=start, end=end)),
                    "3_custos": _total(run_backtest(sub, legacy_targets, eligible=valid[lc], cfg=full_daily, start=start, end=end)),
                    "4_universo_pit": _total(run_backtest(select_panel(bt.panel, nc), pit_targets, eligible=pit_investable[nc],
                                                          cfg=full_daily, start=start, end=end)),
                    "sens_banda_5pp": _total(run_backtest(select_panel(bt.panel, nc), pit_targets, eligible=pit_investable[nc],
                                                          cfg=full_band, start=start, end=end)),
                    "sens_deslistagem_100": _total(run_backtest(select_panel(bt.panel, nc), pit_targets,
                                                                eligible=pit_investable[nc], cfg=daily_recover,
                                                                start=start, end=end)),
                })

    # ---- seleção (selection_backtest.parquet): motor legado run_weighted ----------------------------------
    features = compute_features(market_from_candles(candles))
    legacy_perf, _ = evaluate_selection_legacy(features, regime_series(features), SELECTION_PERIODS, BUDGET_BRL,
                                               SELECTION_REBALANCE_DAYS)
    legacy_total = {(str(s), str(p)): float(v) for s, p, v in
                    zip(legacy_perf["strategy"], legacy_perf["period"], legacy_perf["total_return_pct"], strict=True)}
    same, _ = _all_targets(features, regime_series(features), SELECTION_PERIODS, BUDGET_BRL, SELECTION_REBALANCE_DAYS,
                           SelectionRules(), AllocationRules())
    pit, _ = _all_targets(bt.features, regime_series(bt.features), SELECTION_PERIODS, BUDGET_BRL,
                          SELECTION_REBALANCE_DAYS, SelectionRules(), AllocationRules(), bt.eligible)
    for name in same:
        for period, (start, end) in SELECTION_PERIODS.items():
            rows.append({
                "section": "selecao", "universe": "SELECAO", "strategy": name, "period": period,
                "LEGADO": legacy_total[(name, period)],
                "1_mesmas_premissas": _total(run_backtest(select_panel(bt.panel, list(same[name].columns)),
                                                          _inside(same[name], start), cfg=full_band, start=start, end=end)),
                "2_posicao_inicial": _total(run_backtest(select_panel(bt.panel, list(same[name].columns)), same[name],
                                                         cfg=full_band, start=start, end=end)),
                "3_custos": float("nan"),
                "4_universo_pit": _total(run_backtest(select_panel(bt.panel, list(pit[name].columns)), pit[name],
                                                      eligible=bt.eligible, cfg=full_band, start=start, end=end)),
                "sens_banda_5pp": float("nan"),
                "sens_deslistagem_100": _total(run_backtest(select_panel(bt.panel, list(pit[name].columns)), pit[name],
                                                            eligible=bt.eligible, cfg=band_recover, start=start, end=end)),
            })
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--archive", action="store_true", help="usa data/archive (só as moedas de UNIVERSE)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if args.archive:
        raw, fng = read_archive_candles([s for s in UNIVERSE]), pd.DataFrame()
    else:
        raw, fng = read_ohlcv(list(UNIVERSE)), read_fng()
    if raw.empty:
        print("base vazia", file=sys.stderr)
        return 1
    table = reconcile_engines(raw, fng)
    write_parquet(table, OUT)
    pd.set_option("display.width", 200)
    print(table.round(1).to_string(index=False))
    print(f"\ngravado em {OUT}. Resultados exploratórios: não são validação de estratégia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
