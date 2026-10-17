"""Estudo da camada de seleção e do aporte variável: ela agrega valor contra as referências simples?

Uso (da raiz do projeto, com a base local montada pelo pipeline):

    uv run python research/selection_study.py

Não substitui `strategy_comparison.py` nem `strategy_lab.py` (cujos resultados continuam valendo); acrescenta um
experimento novo, gravado em data/research/selection_study.parquet.

Protocolo (contra o vício de escolher o que deu certo no passado):
    - pesos, limiares e o dimensionamento foram fixados em config.py ANTES deste estudo, por argumento (ver
      README), e não são otimizados aqui;
    - TREINO 2018–2020 e VALIDAÇÃO 2021–2022: a sensibilidade a pesos e limiares é medida só nesses períodos;
    - TESTE 2023 em diante: só mede a configuração padrão; nunca escolhe nada;
    - walk-forward: o mesmo resultado ano a ano, para ver se a vantagem (ou desvantagem) é estável;
    - sem lookahead: cada dia de rebalanceamento usa só candles até o fechamento daquele dia, e uma moeda só entra
      quando ela mesma tem histórico (MIN_SCORE_HISTORY_DAYS) e liquidez naquele dia.

Seções do resultado:
    comparacao     seleção x SMA 200 x comprar e segurar x só BTC x momento simples x DCA, por período
    variantes      o efeito do aporte variável (contra peso igual) e do filtro de regime (bloquear, reduzir, desligado)
    aleatoria      quantos sorteios (mesmo número de moedas e mesma exposição, moedas sorteadas entre as elegíveis)
                   a seleção bateu
    anual          walk-forward: retorno, Sharpe e pior queda por ano
    volatilidade   retorno e Sharpe por regime de volatilidade do BTC (limiares de 30 dias medidos no treino)
    sensibilidade  pesos e limiares alternativos, só treino e validação
    redundancia    correlação de Spearman média (entre moedas, dia a dia, no treino) entre os componentes do score
    viabilidade    com R$ 100: dias com aporte, aportes zerados por ordem mínima/custo, dias em que o alvo passou do
                   orçamento

Limitações: viés de sobrevivência (o universo são moedas que existem hoje: LUNA, FTT e outras que quebraram não
estão na amostra, o que favorece qualquer estratégia de comprar altcoins); spread e slippage estimados, não
medidos; execução no fechamento; uma única história de mercado; sem impostos.

ATENÇÃO (Fase 2): este estudo ainda usa o motor LEGADO (`selection_backtest.run_weighted`): execução ao fechamento do dia do sinal,
exposição que podia passar de 100% com a banda. Seus números NÃO são comparáveis com os do pipeline, que usa o motor único
(`src/transformers/backtest_engine.py`). Migração prevista para a Fase 3 (validação walk-forward); até lá, leia os
resultados como históricos e exploratórios. Comparação dos motores: `research/engine_reconciliation.py`.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab import dca_run, lab_metrics  # noqa: E402

from src.config import (  # noqa: E402
    BUDGET_BRL,
    FEE_PER_SIDE,
    SELECTION_REBALANCE_DAYS,
    TEST_PERIOD,
    TRAIN_PERIOD,
    UNIVERSE,
    VALIDATION_PERIOD,
)
from src.loaders.market_store import read_ohlcv  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.allocation import AllocationRules  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.selection import (  # noqa: E402
    FILTER_OFF,
    FILTER_REDUCE,
    SelectionRules,
    compute_features,
    regime_series,
    score_components,
)
from src.transformers.selection_backtest import (  # noqa: E402
    STRATEGY_BTC,
    STRATEGY_HOLD_ALL,
    STRATEGY_MOMENTUM,
    STRATEGY_SELECTION,
    STRATEGY_SELECTION_EQUAL,
    STRATEGY_SMA200,
    WeightedRun,
    baseline_targets,
    market_returns,
    metrics_row,
    rebalance_days,
    run_weighted,
    selection_targets,
)
from src.transformers.strategies import market_from_candles  # noqa: E402
from src.transformers.universe import select_universe  # noqa: E402

OUT_DIR = Path("data/research")
RANDOM_SIMS = 100
RANDOM_FIRST_SEED = 5000
DCA_EVERY_DAYS = 7

PERIODS: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
    "TREINO": (pd.Timestamp(TRAIN_PERIOD[0], tz="UTC"), pd.Timestamp(VALIDATION_PERIOD[0], tz="UTC") - pd.Timedelta(days=1)),
    "VALIDACAO": (pd.Timestamp(VALIDATION_PERIOD[0], tz="UTC"), pd.Timestamp(VALIDATION_PERIOD[1], tz="UTC")),
    "TESTE": (pd.Timestamp(TEST_PERIOD[0], tz="UTC"), pd.Timestamp(TEST_PERIOD[1], tz="UTC")),
}
IN_SAMPLE = ("TREINO", "VALIDACAO")

STUDY_SCHEMA: dict[str, str] = {
    "section": "string", "strategy": "string", "period": "string",
    "total_return_pct": "float64", "annual_return_pct": "float64", "max_drawdown_pct": "float64",
    "sharpe": "float64", "invested_pct": "float64", "turnover_per_year": "float64", "n_trades": "float64",
    "cost_pct": "float64", "value": "float64", "note": "string",
}
NAN = float("nan")
METRICS = ("total_return_pct", "annual_return_pct", "max_drawdown_pct", "sharpe", "invested_pct", "turnover_per_year",
           "n_trades", "cost_pct")


def _row(section: str, strategy: str, period: str, m: dict[str, object] | None = None, value: float = NAN,
         note: str = "") -> dict[str, object]:
    m = m or {}
    return {
        "section": section, "strategy": strategy, "period": period,
        **{k: m.get(k, NAN) for k in METRICS},
        "value": value, "note": note,
    }


def _run(weights: pd.DataFrame, returns: pd.DataFrame, cost: pd.DataFrame, period: tuple[pd.Timestamp, pd.Timestamp]) -> WeightedRun:
    return run_weighted(weights, returns, cost, period[0], period[1])


def random_targets(features: pd.DataFrame, reference: pd.DataFrame, rules: SelectionRules, rng: np.random.Generator) -> pd.DataFrame:
    """Em cada rebalanceamento, sorteia entre as moedas elegíveis (dados, histórico e liquidez) o mesmo número de
    moedas que a seleção comprou, com a mesma exposição total dividida igualmente. Mantém o mesmo giro: quantas
    moedas a seleção manteve da semana anterior, tantas o sorteio mantém das suas (o resto é sorteado de novo)."""
    out = pd.DataFrame(0.0, index=reference.index, columns=reference.columns)
    previous_sel: set[str] = set()
    current: list[str] = []
    for day in reference.index:
        picks = reference.loc[day]
        chosen_sel = {str(s) for s in picks.index[picks.gt(0)]}
        n, exposure = len(chosen_sel), float(picks.sum())
        today = features.xs(day, level="timestamp")
        ok = (
            today["has_candle"] & today["history_days"].fillna(0).ge(rules.min_history_days)
            & today["avg_volume_30d_usd"].fillna(0).ge(rules.min_volume_usd)
        )
        pool = [str(s) for s in today.index[ok] if s in out.columns]
        kept_n = len(chosen_sel & previous_sel)
        kept = [s for s in current if s in pool][:kept_n]
        rest = [s for s in pool if s not in kept]
        draw = min(max(n - len(kept), 0), len(rest))
        current = kept + ([str(x) for x in rng.choice(rest, size=draw, replace=False)] if draw > 0 else [])
        if current and exposure > 0:
            out.loc[day, current] = exposure / len(current)
        previous_sel = chosen_sel
    return out


def btc_vol_regimes(returns: pd.DataFrame, regime_symbol: str) -> pd.Series:
    """BAIXA / MEDIA / ALTA volatilidade de 30 dias do BTC, com limiares (terços) medidos só no TREINO."""
    vol = returns[regime_symbol].rolling(30, min_periods=25).std() * np.sqrt(365)
    train = vol.loc[PERIODS["TREINO"][0]:PERIODS["TREINO"][1]].dropna()
    lo, hi = float(train.quantile(1 / 3)), float(train.quantile(2 / 3))
    label = np.select([vol.le(lo), vol.le(hi), vol.gt(hi)], ["BAIXA", "MEDIA", "ALTA"], "")
    return pd.Series(label, index=vol.index).shift(1).fillna("")  # regime conhecido no fechamento anterior


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raw = read_ohlcv(list(UNIVERSE))
    if raw.empty:
        print("base local vazia: rode `uv run python -m src.pipeline` antes")
        return 1
    universe = select_universe(UNIVERSE, raw)
    candles = clean_candles(raw[raw["symbol"].isin(universe.kept)])
    rules, alloc = SelectionRules(), AllocationRules()
    features = compute_features(market_from_candles(candles), rules)
    regimes = regime_series(features)
    returns, cost = market_returns(features)
    first = min(s for s, _ in PERIODS.values())
    days = [d for d in rebalance_days(features, SELECTION_REBALANCE_DAYS) if d >= first - pd.Timedelta(days=7)]
    every = SELECTION_REBALANCE_DAYS
    rows: list[dict[str, object]] = []

    print(f"universo: {len(universe.kept)} moedas · fora: {dict(universe.dropped)}")
    print(f"{len(days)} rebalanceamentos a cada {every} dias · orçamento R$ {BUDGET_BRL:.0f}")

    # --- comparação principal ------------------------------------------------------------------
    base = selection_targets(features, regimes, days, BUDGET_BRL, rules, alloc)
    targets = {
        STRATEGY_SELECTION: base.variable,
        STRATEGY_SELECTION_EQUAL: base.equal,
        **baseline_targets(features, rules.regime_symbol, days, rules.max_candidates),
    }
    runs: dict[str, dict[str, WeightedRun]] = {}
    for name, w in targets.items():
        runs[name] = {p: _run(w, returns, cost, span) for p, span in PERIODS.items()}
        for p, run in runs[name].items():
            section = "variantes" if name == STRATEGY_SELECTION_EQUAL else "comparacao"
            rows.append(_row(section, name, p, metrics_row(name, p, run, every)))

    close = pd.DataFrame(features["close"].unstack("symbol")).sort_index()
    valid = pd.DataFrame(features["sma_200"].unstack("symbol")).sort_index().notna()
    for p, (start, end) in PERIODS.items():
        dca, lots = dca_run(close, valid, start, end, DCA_EVERY_DAYS, FEE_PER_SIDE)
        m = lab_metrics(dca, FEE_PER_SIDE, lots)
        rows.append(_row("comparacao", "DCA_FIXO", p, {
            "total_return_pct": m["total"], "annual_return_pct": m["annual"], "max_drawdown_pct": m["drawdown"],
            "sharpe": m["sharpe"], "invested_pct": m["invested"], "cost_pct": m["fee_cost"], "n_trades": m["n_trades"],
        }, note="motor do laboratório: só taxa de 0,1%, sem spread"))

    # --- filtro de regime ----------------------------------------------------------------------
    for mode in (FILTER_REDUCE, FILTER_OFF):
        variant = selection_targets(features, regimes, days, BUDGET_BRL, replace(rules, regime_filter=mode),
                                    replace(alloc, regime_filter=mode))
        for p, span in PERIODS.items():
            name = f"SELECAO_REGIME_{mode.upper()}"
            rows.append(_row("variantes", name, p, metrics_row(name, p, _run(variant.variable, returns, cost, span), every)))

    # --- referência aleatória -----------------------------------------------------------------
    for p, span in PERIODS.items():
        own = runs[STRATEGY_SELECTION][p]
        own_m = metrics_row(STRATEGY_SELECTION, p, own, every)
        sims = []
        for i in range(RANDOM_SIMS):
            w = random_targets(features, base.variable, rules, np.random.default_rng(RANDOM_FIRST_SEED + i))
            sims.append(metrics_row("ALEATORIA", p, _run(w, returns, cost, span), every))
        sim = pd.DataFrame(sims)
        beats = float((float(own_m["sharpe"]) > sim["sharpe"]).mean() * 100) if np.isfinite(float(own_m["sharpe"])) else NAN
        rows.append(_row("aleatoria", "ALEATORIA_MEDIA", p, {k: float(sim[k].astype("float64").mean()) for k in METRICS},
                         value=beats, note=f"value = % dos {RANDOM_SIMS} sorteios que a seleção bateu em Sharpe"))

    # --- walk-forward anual -------------------------------------------------------------------
    years = sorted({d.year for d in returns.index if d >= first})
    for year in years:
        span = (pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year}-12-31", tz="UTC"))
        for name in (STRATEGY_SELECTION, STRATEGY_SMA200, STRATEGY_HOLD_ALL, STRATEGY_BTC, STRATEGY_MOMENTUM):
            rows.append(_row("anual", name, str(year), metrics_row(name, str(year), _run(targets[name], returns, cost, span), every)))

    # --- regimes de volatilidade --------------------------------------------------------------
    vol_regime = btc_vol_regimes(returns, rules.regime_symbol)
    for name in (STRATEGY_SELECTION, STRATEGY_SELECTION_EQUAL, STRATEGY_SMA200, STRATEGY_HOLD_ALL, STRATEGY_BTC):
        for p in ("TESTE",):
            daily = runs[name][p].daily
            for label in ("BAIXA", "MEDIA", "ALTA"):
                part = daily[vol_regime.reindex(daily.index).eq(label)]
                if len(part) < 30:
                    continue
                sd = float(part.std())
                rows.append(_row("volatilidade", name, f"{p}:{label}", {
                    "annual_return_pct": float(part.mean() * 365 * 100),
                    "sharpe": float(part.mean() * 365) / (sd * np.sqrt(365)) if sd > 0 else NAN,
                }, value=float(len(part)), note="value = dias no regime"))

    # --- sensibilidade (só treino e validação) ------------------------------------------------
    variants: dict[str, tuple[SelectionRules, AllocationRules]] = {
        "pesos iguais": (replace(rules, weights={"momentum": .25, "stability": .25, "risk": .25, "liquidity": .25}), alloc),
        "momento 60%": (replace(rules, weights={"momentum": .6, "stability": .15, "risk": .15, "liquidity": .1}), alloc),
        "risco 50%": (replace(rules, weights={"momentum": .2, "stability": .15, "risk": .5, "liquidity": .15}), alloc),
        "limiares -10": (replace(rules, score_strong=rules.score_strong - 10, score_moderate=rules.score_moderate - 10), alloc),
        "limiares +10": (replace(rules, score_strong=rules.score_strong + 10, score_moderate=rules.score_moderate + 10), alloc),
        "vol-alvo 20%": (rules, replace(alloc, target_vol=0.20)),
        "vol-alvo 45%": (rules, replace(alloc, target_vol=0.45)),
        "2 condições": (replace(rules, min_conditions=2), alloc),
    }
    in_days = [d for d in days if d <= PERIODS["VALIDACAO"][1]]
    for label, (sr, ar) in variants.items():
        t = selection_targets(features, regimes, in_days, BUDGET_BRL, sr, ar)
        for p in IN_SAMPLE:
            rows.append(_row("sensibilidade", label, p, metrics_row(label, p, _run(t.variable, returns, cost, PERIODS[p]), every)))
    for p in IN_SAMPLE:
        rows.append(_row("sensibilidade", "padrão (config.py)", p, metrics_row("padrão", p, runs[STRATEGY_SELECTION][p], every)))

    # --- redundância dos componentes ---------------------------------------------------------
    comps: list[pd.DataFrame] = []
    train_days = [d for d in days if PERIODS["TREINO"][0] <= d <= PERIODS["TREINO"][1]]
    for day in train_days:
        today = features.xs(day, level="timestamp")
        c = score_components(today, rules)
        extra = today[["ret_7d_pct", "ret_30d_pct", "ret_90d_pct", "rel_btc_90d_pct"]]
        frame = c.join(extra).dropna()
        if len(frame) >= 5:
            comps.append(frame.rank().corr())
    if comps:
        corr = sum(comps[1:], comps[0]) / len(comps)
        for a in corr.index:
            for b in corr.columns:
                if a < b:
                    rows.append(_row("redundancia", f"{a} x {b}", "TREINO", value=float(corr.loc[a, b]),
                                     note=f"Spearman médio em {len(comps)} dias"))

    # --- viabilidade das quantias pequenas ----------------------------------------------------
    alloc_total = base.variable.sum(axis=1) * BUDGET_BRL
    rows += [
        _row("viabilidade", "rebalanceamentos", "TODOS", value=float(len(days))),
        _row("viabilidade", "com aporte > 0", "TODOS", value=float(base.funded_days)),
        _row("viabilidade", "aportes zerados (mínimo/custo)", "TODOS", value=float(base.zeroed_small)),
        _row("viabilidade", "alvo teórico acima do orçamento", "TODOS", value=float(base.capped_days)),
        _row("viabilidade", "aporte médio quando há aporte (R$)", "TODOS",
             value=float(alloc_total[alloc_total.gt(0)].mean()) if alloc_total.gt(0).any() else 0.0),
    ]

    results = pd.DataFrame(rows)[list(STUDY_SCHEMA)].astype(STUDY_SCHEMA)
    write_parquet(results, OUT_DIR / "selection_study.parquet")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.max_rows", 500)
    for section, part in results.groupby("section", sort=False):
        print(f"\n=== {section} ===")
        cols = ["strategy", "period", "total_return_pct", "annual_return_pct", "max_drawdown_pct", "sharpe",
                "invested_pct", "turnover_per_year", "n_trades", "cost_pct", "value"]
        print(part[cols].dropna(axis=1, how="all").round(2).to_string(index=False))
    print(f"\nGravado em {OUT_DIR}/selection_study.parquet ({len(results)} linhas).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
