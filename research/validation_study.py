"""Validação estatística (Fase 3): família pré-registrada de estratégias, walk-forward, bootstrap em blocos e Holm.

Uso (da raiz do projeto):

    uv run python research/validation_study.py               base do arquivo oficial da Binance (data/archive)
    uv run python research/validation_study.py --base market base do pipeline (data/market, com Fear & Greed)
    uv run python research/validation_study.py --n-boot 500  menos reamostras (teste rápido; não use para concluir)

Protocolo `wf-v1` (fixado em código ANTES de executar; mudar qualquer item é um protocolo novo, com outro id):
    dados       todos os pares USDT do arquivo que estiveram no universo point-in-time em algum dia (top 32 por
                volume medido até D, 365 candles próprios; BTC e ETH sempre), inclusive os que pararam de negociar
    dobras      teste anual a partir de 2020-01-01 até o último dia da base; treino ancorado desde o primeiro
                candle; validação = os 730 dias antes da escolha; embargo 0 (métricas diárias marcadas a mercado)
    status      TODO o histórico já foi explorado no desenvolvimento das regras (EXPLORADO_NO_DESENVOLVIMENTO):
                o walk-forward protege a escolha de parâmetros da grade, não o desenho das regras
    família     16 hipóteses: as 7 regras fixas e as 4 grades do projeto em BTC+ETH (PRINCIPAIS), mais a seleção,
                a seleção com peso igual, o momento simples, a regra SMA 200 semanal e a tendência diária no universo
                point-in-time (TODAS). H0_k: Sharpe(k) − Sharpe(referência_k) <= 0; unilateral; alpha = 5%; Holm.
                Hipótese sem teste possível (ex.: pânico sem Fear & Greed) fica na família com p = 1
    referência  comprar e segurar as MESMAS moedas, peso igual, mesma execução, custos, banda e posição inicial;
                só BTC aparece como referência descritiva (fora da família)
    escolha     grades: maior Sharpe na validação de cada dobra entre os candidatos com >= 3 entradas (a regra do
                laboratório antigo)
    incerteza   bootstrap estacionário conjunto, bloco automático (Politis e White), 2.000 reamostras, semente
                20261016, IC percentil de 90%
    critérios   `src/transformers/evidence.py`

Grava em data/research/validation/ (append-only, `src/loaders/experiment_store.py`) e imprime o relatório.
Resultados com dados reais são de um histórico JÁ EXPLORADO: nenhum número aqui é teste intocado nem promessa.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.loaders.archive_store import read_archive_candles  # noqa: E402
from src.loaders.experiment_store import append_table, read_table  # noqa: E402
from src.loaders.market_store import read_fng, read_ohlcv  # noqa: E402
from src.transformers.allocation import AllocationRules  # noqa: E402
from src.transformers.anomaly_detector import classify_history  # noqa: E402
from src.transformers.backtest_engine import ExecutionConfig, MarketPanel, panel_from_candles, run_backtest  # noqa: E402
from src.transformers.bootstrap import BootstrapConfig  # noqa: E402
from src.transformers.costs import CostModel  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.dataset import combined_fingerprint, dataset_manifest  # noqa: E402
from src.transformers.evidence import EvidenceCriteria  # noqa: E402
from src.transformers.experiments import (  # noqa: E402
    PROTOCOL_VERSION,
    STATUS_INVALID,
    STATUS_PENDING,
    STATUS_VALID,
    ExperimentSpec,
    assert_comparable,
    fingerprint,
    registry_rows,
)
from src.transformers.metrics import engine_metrics  # noqa: E402
from src.transformers.point_in_time import PointInTimeRules, universe_history  # noqa: E402
from src.transformers.portfolio_backtest import checked, equal_weight, investable_mask, select_panel  # noqa: E402
from src.transformers.selection import SelectionRules, compute_features, regime_series  # noqa: E402
from src.transformers.selection_backtest import (  # noqa: E402
    STRATEGY_HOLD_ALL,
    STRATEGY_MOMENTUM,
    STRATEGY_SMA200,
    baseline_targets,
    rebalance_days,
    selection_targets,
)
from src.transformers.strategies import market_from_candles  # noqa: E402
from src.transformers.strategy_catalog import GRID_PARAMS, core_signals, trend_signal  # noqa: E402
from src.transformers.trade_simulator import ExitRules  # noqa: E402
from src.transformers.validation import ALL_SCENARIOS, Benchmark, Case, ValidationReport, ValidationSetup, evaluate_family  # noqa: E402
from src.transformers.walk_forward import (  # noqa: E402
    STATUS_EXPLORED,
    Fold,
    WalkForwardPlan,
    make_folds,
    select_per_fold,
    stitch_targets,
)

FAMILY = "fase3-wf-v1"
FIRST_TEST = pd.Timestamp("2020-01-01", tz="UTC")
MIN_VALIDATION_ENTRIES = 3          # regra do laboratório antigo (research/strategy_lab.py)
FNG_MIN_COVERAGE = 0.95             # fração dos dias fora da amostra com Fear & Greed para o pânico ser testável
CORE = "PRINCIPAIS"
WIDE = "TODAS_PIT"
HOLD_CORE = "HOLD_PRINCIPAIS"
HOLD_WIDE_WEEKLY = "HOLD_TODAS_SEMANAL"
HOLD_WIDE_DAILY = "HOLD_TODAS_DIARIO"
BTC_ONLY = "SO_BTC"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fng_coverage(fng: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if fng.empty:
        return 0.0
    days = pd.date_range(start, end, freq="D")
    have = pd.DatetimeIndex(pd.to_datetime(fng["timestamp"], utc=True).dt.floor("D")).unique()
    return float(days.isin(have).mean())


def grid_case(name: str, candidates: dict[str, pd.DataFrame], panel: MarketPanel, cfg: ExecutionConfig,
              folds: tuple[Fold, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Escolha por dobra (validação) e alvos costurados fora da amostra."""
    cols = list(next(iter(candidates.values())).columns)
    sub = select_panel(panel, cols)

    def score(targets: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[float, bool]:
        result = checked(run_backtest(sub, targets, cfg=cfg, start=start, end=end), f"{name} validação")
        m = engine_metrics(result)
        sharpe = m["sharpe"]
        entries = m["n_entries"]
        value = float(sharpe) if isinstance(sharpe, float) else math.nan
        return value, isinstance(entries, int) and entries >= MIN_VALIDATION_ENTRIES

    selection = select_per_fold(candidates, folds, score)
    return stitch_targets(candidates, selection, folds), selection.assign(strategy=name)


def build(base: str) -> dict[str, object]:
    log("lendo a base")
    if base == "archive":
        raw, fng = read_archive_candles(), read_fng()
    else:
        raw, fng = read_ohlcv(list(config.UNIVERSE)), read_fng()
    if raw.empty:
        raise SystemExit("base vazia")
    candles_all = clean_candles(raw)
    log(f"{candles_all['symbol'].nunique()} pares, {len(candles_all)} candles; universo point-in-time")
    pit = universe_history(candles_all, PointInTimeRules())
    eligible_all = pit.pivot(index="timestamp", columns="symbol", values="eligible").fillna(False).astype(bool)
    ever = sorted(set(eligible_all.columns[eligible_all.any()]) | set(config.RECOMMENDED))
    candles = candles_all[candles_all["symbol"].isin(ever)]
    eligible = eligible_all[ever]
    manifest = dataset_manifest(candles)
    log(f"{len(ever)} pares já estiveram no universo; histórico, indicadores e painel")
    history = classify_history(candles, fng)
    features = compute_features(market_from_candles(candles))
    model = CostModel()
    panel = panel_from_candles(candles, model)
    return {"candles": candles, "eligible": eligible, "history": history, "features": features, "panel": panel,
            "fng": fng, "model": model, "data_fingerprint": combined_fingerprint(manifest),
            "n_symbols": len(ever), "n_candles": len(candles), "last_day": pd.Timestamp(candles["timestamp"].max()).floor("D"),
            "first_day": pd.Timestamp(candles["timestamp"].min()).floor("D")}


def make_cases(d: dict[str, object], folds: tuple[Fold, ...]) -> tuple[list[Case], list[Benchmark], list[Benchmark], pd.DataFrame]:
    history = d["history"]
    features = d["features"]
    panel = d["panel"]
    eligible = d["eligible"]
    model = d["model"]
    fng = d["fng"]
    assert isinstance(history, pd.DataFrame) and isinstance(features, pd.DataFrame) and isinstance(eligible, pd.DataFrame)
    assert isinstance(panel, MarketPanel) and isinstance(model, CostModel) and isinstance(fng, pd.DataFrame)
    start, end = folds[0].test_start, folds[-1].test_end
    daily_cfg = ExecutionConfig(costs=model, rebalance_band=0.0)
    weekly_cfg = ExecutionConfig(costs=model, rebalance_band=config.REBALANCE_BAND)
    investable = investable_mask(history, eligible)
    core = [s for s in config.RECOMMENDED if s in investable.columns]
    inv_core = investable[core]
    ones = pd.DataFrame(1.0, index=inv_core.index, columns=core)

    cases: list[Case] = []
    selections: list[pd.DataFrame] = []
    coverage = fng_coverage(fng, start, end)
    log("estratégias de BTC+ETH")
    candles = d["candles"]
    assert isinstance(candles, pd.DataFrame)
    market = market_from_candles(candles[candles["symbol"].isin(core)])
    for spec in core_signals(history[history["symbol"].isin(core)], market):
        if spec.grid:
            candidates = {k: equal_weight(v[core], inv_core) for k, v in spec.grid.items()}
            log(f"walk-forward {spec.name}: {len(candidates)} candidatos x {len(folds)} dobras")
            targets, sel = grid_case(spec.name, candidates, panel, daily_cfg, folds)
            selections.append(sel)
            chosen = sel[sel["chosen"]].groupby("fold_label")["candidate"].first().to_dict()
            cases.append(Case(spec.name, CORE, HOLD_CORE, daily_cfg, targets, True,
                              {"grid": GRID_PARAMS[spec.name], "chosen_by_fold": chosen}, candidates))
            continue
        assert spec.signal is not None
        invalid = None
        if spec.requires_fng and coverage < FNG_MIN_COVERAGE:
            invalid = (f"feature Fear & Greed ausente em {1 - coverage:.0%} dos dias fora da amostra: o pânico não pode "
                       "ser avaliado (ausência não é tratada como valor zero)")
        cases.append(Case(spec.name, CORE, HOLD_CORE, daily_cfg, equal_weight(spec.signal[core], inv_core), True,
                          dict(spec.params), {k: equal_weight(v[core], inv_core) for k, v in spec.variants.items()},
                          invalid_reason=invalid))

    log("estratégias do universo point-in-time (seleção semanal)")
    days = [x for x in rebalance_days(features, config.SELECTION_REBALANCE_DAYS) if x >= start - pd.Timedelta(days=7)]
    regime = regime_series(features)
    rules = SelectionRules()
    sel_t = selection_targets(features, regime, days, config.BUDGET_BRL, rules, AllocationRules(), eligible)
    variants_sel: dict[str, pd.DataFrame] = {}
    variants_eq: dict[str, pd.DataFrame] = {}
    for vname, vr in {"score_55_40": replace(rules, score_strong=55.0, score_moderate=40.0),
                      "score_75_60": replace(rules, score_strong=75.0, score_moderate=60.0),
                      "condicoes_2": replace(rules, min_conditions=2), "condicoes_4": replace(rules, min_conditions=4)}.items():
        log(f"seleção, variação {vname}")
        vt = selection_targets(features, regime, days, config.BUDGET_BRL, vr, AllocationRules(), eligible)
        variants_sel[vname], variants_eq[vname] = vt.variable, vt.equal
    base_t = baseline_targets(features, rules.regime_symbol, days, rules.max_candidates, eligible)

    def every(n: int) -> list[pd.Timestamp]:
        return [x for x in rebalance_days(features, n) if x >= start - pd.Timedelta(days=n)]

    cases += [
        Case("SELECAO", WIDE, HOLD_WIDE_WEEKLY, weekly_cfg, sel_t.variable, True,
             {"rules": asdict(rules), "budget_brl": config.BUDGET_BRL}, variants_sel),
        Case("SELECAO_PESO_IGUAL", WIDE, HOLD_WIDE_WEEKLY, weekly_cfg, sel_t.equal, True, {"rules": asdict(rules)}, variants_eq),
        Case("MOMENTO_SIMPLES", WIDE, HOLD_WIDE_WEEKLY, weekly_cfg, base_t[STRATEGY_MOMENTUM], True, {"top": 3, "days": 90},
             {f"top{k}": baseline_targets(features, rules.regime_symbol, days, k, eligible)[STRATEGY_MOMENTUM] for k in (2, 5)}),
        Case("TENDENCIA_SMA200_SEMANAL", WIDE, HOLD_WIDE_WEEKLY, weekly_cfg, base_t[STRATEGY_SMA200], True, {"every": 7},
             {f"a_cada_{k}d": baseline_targets(features, rules.regime_symbol, every(k), rules.max_candidates, eligible)[STRATEGY_SMA200]
              for k in (5, 10)}),
    ]
    log("tendência diária no universo point-in-time")
    wide_cols = list(investable.columns)
    cases.append(Case("TENDENCIA_TODAS", WIDE, HOLD_WIDE_DAILY, daily_cfg, equal_weight(trend_signal(history)[wide_cols], investable),
                      True, {"sma": 200, "btc_filter": True, "stop": -0.20},
                      {"sma150": equal_weight(trend_signal(history, 150)[wide_cols], investable),
                       "sma250": equal_weight(trend_signal(history, 250)[wide_cols], investable),
                       "sem_stop": equal_weight(trend_signal(history, 200, None)[wide_cols], investable)}))
    benchmarks = [
        Benchmark(HOLD_CORE, CORE, daily_cfg, equal_weight(ones, inv_core)),
        Benchmark(HOLD_WIDE_WEEKLY, WIDE, weekly_cfg, base_t[STRATEGY_HOLD_ALL]),
        Benchmark(HOLD_WIDE_DAILY, WIDE, daily_cfg,
                  equal_weight(pd.DataFrame(1.0, index=investable.index, columns=wide_cols), investable)),
    ]
    btc = pd.DataFrame(1.0, index=inv_core.index, columns=["BTC/USDT"])
    descriptive = [Benchmark(BTC_ONLY, "BTC", daily_cfg, equal_weight(btc, inv_core[["BTC/USDT"]]))]
    return cases, benchmarks, descriptive, pd.concat(selections, ignore_index=True) if selections else pd.DataFrame()


def btc_regimes(features: pd.DataFrame) -> pd.Series:
    return regime_series(features).astype("string")


def registry(report: ValidationReport, cases: list[Case], benchmarks: list[Benchmark], folds: tuple[Fold, ...], d: dict[str, object],
             config_fp: str, run_id: str, run_ts: pd.Timestamp) -> pd.DataFrame:
    start, end = folds[0].test_start, folds[-1].test_end
    status_data = STATUS_EXPLORED
    limits = ("histórico já explorado no desenvolvimento", "spread e slippage estimados, não medidos",
              "deslistagem inferida pelo fim da série", "universo só Binance spot USDT")
    model = d["model"]
    assert isinstance(model, CostModel)
    data_fp = str(d["data_fingerprint"])
    entries = []
    summary = report.summary.set_index("strategy")
    for c in cases:
        for scenario in ALL_SCENARIOS:
            row = report.scenarios[(report.scenarios["strategy"] == c.name) & (report.scenarios["scenario"] == scenario)]
            metrics = {} if row.empty else {k: row.iloc[0][k] for k in ("sharpe", "cagr_pct", "max_drawdown_pct", "delta_sharpe")}
            validation: dict[str, object] = {}
            if scenario == "BASE" and c.name in summary.index:
                s = summary.loc[c.name]
                validation = {k: s[k] for k in ("delta_sharpe", "delta_sharpe_ci_low", "delta_sharpe_ci_high", "p_value",
                                                "p_holm", "p_maxstat", "positive_fold_share", "stress_min_delta_sharpe",
                                                "variant_positive_share") if k in s.index}
                metrics = {k: s[k] for k in ("n_obs", "total_return_pct", "cagr_pct", "vol_pct", "sharpe", "sortino",
                                             "max_drawdown_pct", "calmar", "exposure_pct", "turnover_per_year", "cost_pct",
                                             "n_entries") if k in s.index}
            category = str(summary.loc[c.name, "category"]) if scenario == "BASE" else ""
            spec = ExperimentSpec(FAMILY, c.name, c.params, c.universe, c.benchmark, scenario, start, end, status_data,
                                  c.cfg.version, c.cfg.costs, c.cfg.rebalance_band, c.cfg.delist_recovery, data_fp, config_fp,
                                  PROTOCOL_VERSION, (*limits, *([c.invalid_reason] if c.invalid_reason else [])))
            entries.append((spec, metrics, validation, category, STATUS_INVALID if c.invalid_reason else STATUS_VALID))
    for b in benchmarks:
        s = summary.loc[b.name]
        spec = ExperimentSpec(FAMILY, b.name, {}, b.universe, "", "BASE", start, end, status_data, b.cfg.version, b.cfg.costs,
                              b.cfg.rebalance_band, b.cfg.delist_recovery, data_fp, config_fp, PROTOCOL_VERSION, limits)
        entries.append((spec, {k: s[k] for k in ("n_obs", "total_return_pct", "cagr_pct", "sharpe", "max_drawdown_pct")},
                        {}, "REFERENCIA", STATUS_VALID))
    # Protocolo prospectivo: registrado agora, avaliado só com dados posteriores ao último dia explorado.
    last_day = pd.Timestamp(str(d["last_day"]))
    for name in ("TENDENCIA", "SELECAO"):
        c = next(x for x in cases if x.name == name)
        spec = ExperimentSpec(f"{FAMILY}-prospectivo", name, c.params, c.universe, c.benchmark, "BASE",
                              last_day + pd.Timedelta(days=1), last_day + pd.Timedelta(days=365), "PROSPECTIVO",
                              c.cfg.version, c.cfg.costs, c.cfg.rebalance_band, c.cfg.delist_recovery, "a-coletar", config_fp,
                              PROTOCOL_VERSION, ("avaliação só depois de 365 dias de dados novos, com as mesmas regras e testes",))
        entries.append((spec, {}, {"min_days": 365}, "", STATUS_PENDING))
    rows = registry_rows(entries, run_id, run_ts, read_table("registry"))
    assert_comparable(rows[(rows["family"] == FAMILY) & (rows["scenario"] == "BASE")])
    return rows


def report_text(report: ValidationReport, d: dict[str, object], folds: tuple[Fold, ...], sel: pd.DataFrame) -> str:
    s = report.summary
    lines = [f"dados: {d['n_symbols']} pares, {d['n_candles']} candles, SHA-256 {str(d['data_fingerprint'])[:16]}",
             f"fora da amostra: {folds[0].test_start:%Y-%m-%d} a {folds[-1].test_end:%Y-%m-%d} ({len(folds)} dobras, todas "
             f"{STATUS_EXPLORED}); bloco médio {report.block:.1f} dias"]
    cols = ["strategy", "universe", "n_obs", "n_entries", "cagr_pct", "sharpe", "sharpe_ci_low", "sharpe_ci_high",
            "max_drawdown_pct", "delta_sharpe", "delta_sharpe_ci_low", "delta_sharpe_ci_high", "p_value", "p_holm", "p_maxstat",
            "positive_fold_share", "stress_min_delta_sharpe", "stress_worst", "variant_positive_share", "category"]
    view = s[[c for c in cols if c in s.columns]]
    lines.append(view.round(3).to_string(index=False))
    lines.append("\nmotivos:")
    for _, r in s[s["role"].eq("ESTRATEGIA")].iterrows():
        lines.append(f"  {r['strategy']}: {r['category']} — {r['reasons']}")
    lines.append("\ndobras (ΔSharpe contra a referência):")
    lines.append(report.folds.pivot(index="strategy", columns="fold", values="delta_sharpe").round(2).to_string())
    lines.append("\ncenários (ΔSharpe):")
    lines.append(report.scenarios.pivot(index="strategy", columns="scenario", values="delta_sharpe").round(2).to_string())
    lines.append("\nsensibilidade ao bloco (IC 90% da ΔSharpe):")
    b = report.blocks.assign(ci=lambda x: x["ci_low"].round(2).astype(str) + " a " + x["ci_high"].round(2).astype(str))
    lines.append(b.pivot(index="strategy", columns="block", values="ci").to_string())
    if not sel.empty:
        lines.append("\nescolhas do walk-forward:")
        lines.append(sel[sel["chosen"]].pivot(index="strategy", columns="fold_label", values="candidate").to_string())
    if not report.regimes.empty:
        lines.append("\nregimes do BTC (estado no fechamento anterior), Sharpe:")
        lines.append(report.regimes.pivot(index="strategy", columns="regime", values="sharpe").round(2).to_string())
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validação estatística (Fase 3)")
    parser.add_argument("--base", choices=["archive", "market"], default="archive")
    parser.add_argument("--n-boot", type=int, default=2000)
    parser.add_argument("--no-save", action="store_true", help="só imprime (não grava no registro)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    run_ts = pd.Timestamp.now(tz="UTC").floor("s")
    t0 = time.time()
    d = build(args.base)
    first_day, last_day = pd.Timestamp(str(d["first_day"])), pd.Timestamp(str(d["last_day"]))
    plan = WalkForwardPlan(first_day, FIRST_TEST, last_day, explored_until=last_day)
    folds = make_folds(plan)
    cases, benchmarks, descriptive, sel = make_cases(d, folds)
    boot = BootstrapConfig(n_boot=args.n_boot)
    criteria = EvidenceCriteria()
    features = d["features"]
    panel = d["panel"]
    eligible = d["eligible"]
    assert isinstance(features, pd.DataFrame) and isinstance(panel, MarketPanel) and isinstance(eligible, pd.DataFrame)
    setup = ValidationSetup(panel=panel, folds=folds, eligible=eligible, boot=boot, criteria=criteria,
                            regimes=btc_regimes(features))
    config_fp = fingerprint({"selection": SelectionRules(), "allocation": AllocationRules(), "exit": ExitRules(),
                             "pit": PointInTimeRules(), "grids": GRID_PARAMS, "criteria": criteria, "boot": boot,
                             "plan": plan, "family": [c.name for c in cases], "scenarios": ALL_SCENARIOS,
                             "low_cost": setup.low_cost, "high_cost": setup.high_cost})
    report = evaluate_family(cases, benchmarks, setup, descriptive, progress=log)
    run_id = f"{run_ts:%Y%m%dT%H%M%SZ}-{config_fp[:8]}"
    rows = registry(report, cases, [*benchmarks, *descriptive], folds, d, config_fp, run_id, run_ts)
    print(report_text(report, d, folds, sel))
    print(f"\nconfiguração {config_fp} · execução {run_id} · {time.time() - t0:.0f} s")
    if not args.no_save:
        append_table("registry", rows)
        tables = {"summary": report.summary, "folds": report.folds, "scenarios": report.scenarios, "variants": report.variants,
                  "blocks": report.blocks, "regimes": report.regimes, "wf_selection": sel,
                  "returns": report.returns.rename_axis("timestamp").reset_index()}
        for name, table in tables.items():
            append_table(name, table.assign(run_id=run_id, data_fingerprint=str(d["data_fingerprint"])))
        print(f"gravado em data/research/validation/ ({len(rows)} linhas no registro)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
