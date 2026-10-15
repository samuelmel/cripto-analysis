"""Laboratório de estratégias: compara tudo em carteira, com treino, validação e teste separados.

Uso (da raiz do projeto, com a base local montada pelo pipeline):

    uv run python research/strategy_lab.py

Protocolo (contra o vício de escolher o que deu certo no passado):
    TREINO     2018-01 a 2020-12   olhar à vontade
    VALIDAÇÃO  2021-01 a 2022-12   aqui se escolhem os parâmetros (maior Sharpe de cada estratégia, com ao menos
                                   3 operações na validação)
    TESTE      2023 em diante      só se mede, com os parâmetros já escolhidos; nunca entra na escolha

As estratégias de `strategy_comparison.py` entram como estão (parâmetros fixos); o laboratório acrescenta
DCA, Donchian, Bollinger, RSI, rompimento com volume e uma referência aleatória (mesma exposição, timing
sorteado, sementes fixas). Motor: o do pipeline (taxa de 0,1% por lado, posição de t vale para t+1).

Grava em data/research/: strategy_lab.parquet (resultados) e strategy_lab_grid.parquet (todos os parâmetros
testados, só com treino e validação). Mostra tudo, inclusive o que perde.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab import (  # noqa: E402
    GRIDS,
    Market,
    dca_run,
    describe,
    lab_metrics,
    market_from_candles,
    random_reference,
)
from strategy_comparison import build_strategies  # noqa: E402

from src.config import FEE_PER_SIDE, RECOMMENDED, TEST_PERIOD, TRAIN_PERIOD, UNIVERSE, VALIDATION_PERIOD  # noqa: E402
from src.loaders.market_store import read_fng, read_ohlcv  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.anomaly_detector import classify_history  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.trade_simulator import run_portfolio  # noqa: E402
from src.transformers.universe import select_universe  # noqa: E402

OUT_DIR = Path("data/research")
RANDOM_SIMS = 200
RANDOM_FIRST_SEED = 1000
DCA_EVERY_DAYS = 7
MIN_VALIDATION_TRADES = 3  # parâmetro com menos operações que isso na validação não é elegível (amostra pequena demais)

PERIODS: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
    "TREINO": (pd.Timestamp(TRAIN_PERIOD[0], tz="UTC"), pd.Timestamp(VALIDATION_PERIOD[0], tz="UTC") - pd.Timedelta(days=1)),
    "VALIDACAO": (pd.Timestamp(VALIDATION_PERIOD[0], tz="UTC"), pd.Timestamp(VALIDATION_PERIOD[1], tz="UTC")),
    "TESTE": (pd.Timestamp(TEST_PERIOD[0], tz="UTC"), pd.Timestamp(TEST_PERIOD[1], tz="UTC")),
}

RESULT_SCHEMA: dict[str, str] = {
    "universe": "string", "strategy": "string", "params": "string", "period": "string", "selected_on": "string",
    "start": "datetime64[ns, UTC]", "end": "datetime64[ns, UTC]",
    "total_return_pct": "float64", "annual_return_pct": "float64", "max_drawdown_pct": "float64",
    "sharpe": "float64", "invested_pct": "float64", "n_trades": "float64", "win_rate_pct": "float64",
    "profit_factor": "float64", "turnover_per_year": "float64", "fee_cost_pct": "float64",
    "beats_random_pct": "float64", "random_sims": "Int64",
}
GRID_SCHEMA: dict[str, str] = {
    "universe": "string", "strategy": "string", "params": "string", "period": "string",
    "total_return_pct": "float64", "sharpe": "float64", "n_trades": "float64", "selected": "bool",
}

NAN = float("nan")


def _row(universe: str, strategy: str, params: str, period: str, selected_on: str, m: dict[str, float],
         start: pd.Timestamp, end: pd.Timestamp, beats: float = NAN, sims: int | None = None) -> dict[str, object]:
    return {
        "universe": universe, "strategy": strategy, "params": params, "period": period, "selected_on": selected_on,
        "start": start, "end": end,
        "total_return_pct": m["total"], "annual_return_pct": m["annual"], "max_drawdown_pct": m["drawdown"],
        "sharpe": m["sharpe"], "invested_pct": m["invested"], "n_trades": m["n_trades"], "win_rate_pct": m["win_rate"],
        "profit_factor": m["profit_factor"], "turnover_per_year": m["turnover"], "fee_cost_pct": m["fee_cost"],
        "beats_random_pct": beats, "random_sims": sims,
    }


def run_lab(history: pd.DataFrame, market: Market, universes: dict[str, tuple[str, ...]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resultados de todas as estratégias nos três períodos e a grade de parâmetros (treino e validação)."""
    existing, ret, valid = build_strategies(history)
    close = market.close.reindex(index=ret.index, columns=ret.columns)
    market = Market(close, *(f.reindex(index=ret.index, columns=ret.columns) for f in (market.high, market.low, market.volume)))

    rows: list[dict[str, object]] = []
    grid: list[dict[str, object]] = []
    for universe, symbols in universes.items():
        cols = [s for s in symbols if s in ret.columns]

        def evaluate(positions: pd.DataFrame, period: str) -> tuple[dict[str, float], pd.DataFrame]:
            start, end = PERIODS[period]
            run = run_portfolio(positions[cols], ret[cols], valid[cols], start, end, FEE_PER_SIDE)
            return lab_metrics(run, FEE_PER_SIDE), positions

        chosen: dict[str, tuple[str, pd.DataFrame, str]] = {}  # nome -> (params, posições, como foi escolhida)
        for name, positions in existing.items():
            chosen[name] = ("", positions, "fixa")
        for name, (signal, candidates) in GRIDS.items():
            scored: list[tuple[float, dict[str, float], pd.DataFrame]] = []
            for params in candidates:
                positions = signal(market, **params)
                metrics = {p: evaluate(positions, p)[0] for p in ("TREINO", "VALIDACAO")}
                score = metrics["VALIDACAO"]["sharpe"]
                eligible = np.isfinite(score) and metrics["VALIDACAO"]["n_trades"] >= MIN_VALIDATION_TRADES
                scored.append((score if eligible else -np.inf, params, positions))
                for period, m in metrics.items():
                    grid.append({"universe": universe, "strategy": name, "params": describe(params), "period": period,
                                 "total_return_pct": m["total"], "sharpe": m["sharpe"], "n_trades": m["n_trades"],
                                 "selected": False})
            best = max(scored, key=lambda t: t[0])
            for g in grid:
                if g["universe"] == universe and g["strategy"] == name and g["params"] == describe(best[1]):
                    g["selected"] = True
            chosen[name] = (describe(best[1]), best[2], "validação")

        for name, (params, positions, how) in chosen.items():
            for period, (start, end) in PERIODS.items():
                m, _ = evaluate(positions, period)
                beats, sims = NAN, None
                if not name.startswith("1 "):  # comprar e segurar não tem timing a sortear
                    ref = random_reference(positions[cols], ret[cols], valid[cols], start, end, FEE_PER_SIDE,
                                           RANDOM_SIMS, RANDOM_FIRST_SEED)
                    beats, sims = float((m["total"] > ref["total"]).mean()) * 100.0, len(ref)
                    mean = {k: float(ref[k].mean()) for k in ("total", "annual", "drawdown", "sharpe", "invested")}
                    rows.append(_row(universe, f"Aleatória (mesma exposição de {name})", f"média de {len(ref)} sorteios",
                                     period, "sementes fixas", {**mean, "n_trades": NAN, "win_rate": NAN, "profit_factor": NAN,
                                                                "turnover": NAN, "fee_cost": NAN}, start, end))
                rows.append(_row(universe, name, params, period, how, m, start, end, beats, sims))

        for period, (start, end) in PERIODS.items():
            run, lots = dca_run(close[cols], valid[cols], start, end, DCA_EVERY_DAYS, FEE_PER_SIDE)
            rows.append(_row(universe, "DCA fixo", f"a cada {DCA_EVERY_DAYS} dias", period, "fixa",
                             lab_metrics(run, FEE_PER_SIDE, lots), start, end))

    results = pd.DataFrame(rows)[list(RESULT_SCHEMA)].astype(RESULT_SCHEMA)
    grid_df = pd.DataFrame(grid)[list(GRID_SCHEMA)].astype(GRID_SCHEMA)
    return results, grid_df


def show(results: pd.DataFrame) -> str:
    cols = ["strategy", "params", "total_return_pct", "annual_return_pct", "max_drawdown_pct", "sharpe", "invested_pct",
            "n_trades", "win_rate_pct", "profit_factor", "turnover_per_year", "fee_cost_pct", "beats_random_pct"]
    names = {"strategy": "estratégia", "params": "parâmetros", "total_return_pct": "total %", "annual_return_pct": "ao ano %",
             "max_drawdown_pct": "pior queda %", "sharpe": "sharpe", "invested_pct": "comprado %", "n_trades": "operações",
             "win_rate_pct": "acerto %", "profit_factor": "fator lucro", "turnover_per_year": "trocas/ano",
             "fee_cost_pct": "taxas %", "beats_random_pct": "bate aleat. %"}
    lines = []
    for (universe, period), part in results.groupby(["universe", "period"], sort=False):
        lines.append(f"\n=== {universe} · {period} · {part['start'].iloc[0]:%Y-%m-%d} a {part['end'].iloc[0]:%Y-%m-%d} "
                     f"· taxa {FEE_PER_SIDE:.1%} por lado ===")
        view = part[cols].rename(columns=names).sort_values("sharpe", ascending=False)
        lines.append(view.round(1).to_string(index=False))
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raw = read_ohlcv(list(UNIVERSE))
    if raw.empty:
        print("base local vazia: rode `uv run python -m src.pipeline` antes")
        return 1
    kept = select_universe(UNIVERSE, raw).kept
    candles = clean_candles(raw[raw["symbol"].isin(kept)])
    history = classify_history(candles, read_fng())
    results, grid = run_lab(history, market_from_candles(candles), {"PRINCIPAIS": RECOMMENDED, "TODAS": kept})
    write_parquet(results, OUT_DIR / "strategy_lab.parquet")
    write_parquet(grid, OUT_DIR / "strategy_lab_grid.parquet")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(show(results))
    print(f"\nGravado em {OUT_DIR}/ ({len(results)} linhas de resultado, {len(grid)} de grade).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
