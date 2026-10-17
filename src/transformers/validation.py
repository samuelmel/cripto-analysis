"""Validação estatística de uma família de estratégias fora da amostra, contra referências com as mesmas premissas.

Puro (CLAUDE.md §1): recebe preços (MarketPanel), alvos já construídos (sem olhar para frente), dobras walk-forward
e configurações; devolve tabelas. Quem lê dados e grava resultados é `research/validation_study.py`.

O que é medido, para cada estratégia (`Case`) e a sua referência PRIMÁRIA (`Benchmark`: comprar e segurar as
mesmas moedas, no mesmo universo, com a mesma execução, custos, banda e posição inicial):
    BASE          uma simulação contínua no motor único sobre todo o período fora da amostra (as dobras de teste
                  em sequência; os parâmetros mudam na fronteira de cada dobra, sem zerar a carteira)
    dobras        as métricas de cada dobra cortadas da simulação BASE (variação entre janelas)
    cenários      a mesma estratégia E a mesma referência refeitas com outra premissa (custo baixo/alto, atraso de
                  1 dia, início de cada dobra em caixa, deslistagem com 100% de recuperação, 2% dos candles
                  removidos): sensibilidade às premissas, distinta da incerteza estatística
    variações     a estratégia com parâmetros moderadamente diferentes (ou, para as de grade, todos os candidatos)
    incerteza     bootstrap estacionário pareado e CONJUNTO (os mesmos dias reamostrados para todas as séries):
                  intervalos de Sharpe, retorno anualizado e das diferenças contra a referência; p-valor
                  unilateral de H0: ΔSharpe <= 0; Holm na família; ajuste pelo máximo; sensibilidade ao bloco
    regimes       retorno e Sharpe por estado do mercado conhecido no fechamento anterior (descritivo)
Depois, `evidence.classify` com os critérios pré-registrados.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .backtest_engine import BacktestResult, ExecutionConfig, MarketPanel, run_backtest
from .bootstrap import (
    BootstrapConfig,
    Estimate,
    Resampler,
    bootstrap_difference,
    bootstrap_statistic,
    cagr_stat,
    make_resampler,
    max_stat_pvalues,
    optimal_block_length,
    sharpe_stat,
    stationary_indices,
)
from .costs import CostModel
from .evidence import EvidenceCriteria, EvidenceInput, classify
from .metrics import MetricConventions, engine_metrics, return_metrics
from .multiple_testing import holm
from .portfolio_backtest import checked, select_panel
from .walk_forward import Fold, delay_targets

SCENARIO_BASE = "BASE"
SCENARIO_LOW_COST = "CUSTO_BAIXO"
SCENARIO_HIGH_COST = "CUSTO_ALTO"
SCENARIO_DELAY = "ATRASO_1D"
SCENARIO_CASH_START = "INICIO_EM_CAIXA"
SCENARIO_DELIST_FULL = "DESLISTAGEM_100"
SCENARIO_PARTIAL_DATA = "DADOS_PARCIAIS"
STRESS_SCENARIOS: tuple[str, ...] = (
    SCENARIO_HIGH_COST, SCENARIO_DELAY, SCENARIO_CASH_START, SCENARIO_DELIST_FULL, SCENARIO_PARTIAL_DATA,
)
ALL_SCENARIOS: tuple[str, ...] = (SCENARIO_BASE, SCENARIO_LOW_COST, *STRESS_SCENARIOS)


@dataclass(frozen=True)
class Benchmark:
    name: str
    universe: str
    cfg: ExecutionConfig
    targets: pd.DataFrame


@dataclass(frozen=True)
class Case:
    name: str
    universe: str
    benchmark: str
    cfg: ExecutionConfig
    targets: pd.DataFrame                       # alvos fora da amostra (grade: já costurados por dobra)
    timing: bool = True                         # exige número mínimo de entradas
    params: Mapping[str, object] = field(default_factory=dict)
    variants: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    invalid_reason: str | None = None
    family_member: bool = True


@dataclass(frozen=True)
class ValidationSetup:
    panel: MarketPanel
    folds: tuple[Fold, ...]
    eligible: pd.DataFrame | None = None
    boot: BootstrapConfig = BootstrapConfig()
    criteria: EvidenceCriteria = EvidenceCriteria()
    conventions: MetricConventions = MetricConventions()
    block_sensitivity: tuple[float, ...] = (5.0, 20.0, 60.0)
    low_cost: CostModel = CostModel(fee_rate=0.00075, slippage=0.00025,
                                    spread_tiers=((500_000_000.0, 0.0001), (50_000_000.0, 0.00025), (0.0, 0.00075)))
    high_cost: CostModel = CostModel(fee_rate=0.001, slippage=0.001,
                                     spread_tiers=((500_000_000.0, 0.0004), (50_000_000.0, 0.001), (0.0, 0.003)))
    partial_data_fraction: float = 0.02
    partial_data_seed: int = 7
    regimes: pd.Series | None = None            # rótulo do estado do mercado por dia (conhecido no fechamento)

    @property
    def start(self) -> pd.Timestamp:
        return self.folds[0].test_start

    @property
    def end(self) -> pd.Timestamp:
        return self.folds[-1].test_end


@dataclass(frozen=True)
class ValidationReport:
    summary: pd.DataFrame
    folds: pd.DataFrame
    scenarios: pd.DataFrame
    variants: pd.DataFrame
    blocks: pd.DataFrame
    regimes: pd.DataFrame
    returns: pd.DataFrame          # retornos diários BASE de cada estratégia e referência (para reprodução)
    block: float                   # comprimento médio do bloco usado no bootstrap conjunto


# ---------------------------------------------------------------------------------------------
# Simulação
# ---------------------------------------------------------------------------------------------

def partial_panel(panel: MarketPanel, fraction: float, seed: int) -> MarketPanel:
    """O painel com `fraction` dos candles (dia, moeda) removidos ao acaso (abertura e fechamento juntos)."""
    rng = np.random.default_rng(seed)
    drop = rng.random(panel.close.shape) < fraction
    return MarketPanel(panel.open.mask(drop), panel.close.mask(drop), panel.half_spread)


def simulate(
    panel: MarketPanel,
    targets: pd.DataFrame,
    cfg: ExecutionConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    eligible: pd.DataFrame | None,
    label: str,
) -> BacktestResult:
    """Uma simulação reconciliada no motor único, só com as colunas dos alvos."""
    sub = select_panel(panel, [str(c) for c in targets.columns])
    return checked(run_backtest(sub, targets, eligible=eligible, cfg=cfg, start=start, end=end), label)


def _cash_start_returns(setup: ValidationSetup, targets: pd.DataFrame, cfg: ExecutionConfig, label: str) -> pd.Series:
    """Cada dobra simulada sozinha, começando em caixa e só com decisões de dentro dela; dobras concatenadas."""
    parts = []
    for f in setup.folds:
        inside = targets.loc[(targets.index >= f.test_start) & (targets.index <= f.test_end)]
        parts.append(simulate(setup.panel, inside, cfg, f.test_start, f.test_end, setup.eligible, f"{label}/{f.label}").returns)
    return pd.Series(pd.concat(parts))


def scenario_returns(setup: ValidationSetup, targets: pd.DataFrame, cfg: ExecutionConfig, scenario: str, label: str) -> pd.Series:
    """Retornos diários fora da amostra de `targets` sob o cenário."""
    s, e, el, panel = setup.start, setup.end, setup.eligible, setup.panel
    if scenario == SCENARIO_BASE:
        return simulate(panel, targets, cfg, s, e, el, label).returns
    if scenario == SCENARIO_LOW_COST:
        return simulate(panel, targets, replace(cfg, costs=setup.low_cost), s, e, el, label).returns
    if scenario == SCENARIO_HIGH_COST:
        return simulate(panel, targets, replace(cfg, costs=setup.high_cost), s, e, el, label).returns
    if scenario == SCENARIO_DELAY:
        return simulate(panel, delay_targets(targets, 1), cfg, s, e, _delayed(el), label).returns
    if scenario == SCENARIO_DELIST_FULL:
        return simulate(panel, targets, replace(cfg, delist_recovery=1.0), s, e, el, label).returns
    if scenario == SCENARIO_PARTIAL_DATA:
        damaged = partial_panel(panel, setup.partial_data_fraction, setup.partial_data_seed)
        return simulate(damaged, targets, cfg, s, e, el, label).returns
    if scenario == SCENARIO_CASH_START:
        return _cash_start_returns(setup, targets, cfg, label)
    raise ValueError(f"cenário desconhecido: {scenario}")


def _delayed(eligible: pd.DataFrame | None) -> pd.DataFrame | None:
    """O universo conhecido em D continua valendo para a decisão atrasada de D+1 (mesmo atraso dos alvos)."""
    return None if eligible is None else eligible.set_axis(eligible.index + pd.Timedelta(days=1), axis=0)


# ---------------------------------------------------------------------------------------------
# Métricas auxiliares
# ---------------------------------------------------------------------------------------------

def _sharpe(r: pd.Series, conventions: MetricConventions) -> float:
    m = return_metrics(r, None, conventions)
    value = m["sharpe"]
    return float(value) if isinstance(value, float) else math.nan


def _floats(r: pd.Series) -> np.ndarray:
    return np.asarray(r.to_numpy(dtype="float64"), dtype=np.float64)


def _fold_rows(case: Case, r: pd.Series, b: pd.Series, setup: ValidationSetup) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for f in setup.folds:
        rs = r.loc[f.test_start:f.test_end]
        bs = b.loc[f.test_start:f.test_end]
        ms = return_metrics(rs, None, setup.conventions)
        mb = return_metrics(bs, None, setup.conventions)
        rows.append({
            "strategy": case.name, "benchmark": case.benchmark, "fold": f.label, "data_status": f.data_status,
            "start": f.test_start, "end": f.test_end, "n_obs": len(rs),
            "total_return_pct": ms["total_return_pct"], "benchmark_total_return_pct": mb["total_return_pct"],
            "sharpe": ms["sharpe"], "benchmark_sharpe": mb["sharpe"],
            "delta_sharpe": _diff(ms["sharpe"], mb["sharpe"]),
            "max_drawdown_pct": ms["max_drawdown_pct"], "benchmark_max_drawdown_pct": mb["max_drawdown_pct"],
        })
    return rows


def _diff(a: object, b: object) -> float:
    x = float(a) if isinstance(a, float | int) else math.nan
    y = float(b) if isinstance(b, float | int) else math.nan
    return x - y


def _regime_rows(name: str, r: pd.Series, regimes: pd.Series | None, conventions: MetricConventions) -> list[dict[str, object]]:
    if regimes is None:
        return []
    known = regimes.reindex(pd.DatetimeIndex(r.index) - pd.Timedelta(days=1))  # estado no fechamento ANTERIOR ao retorno do dia
    known.index = r.index
    rows: list[dict[str, object]] = []
    for label in sorted(known.dropna().astype(str).unique()):
        part = r[known.astype(str).eq(label).fillna(False).to_numpy()]
        sd = float(part.std(ddof=1)) if len(part) > 1 else math.nan
        rows.append({"strategy": name, "regime": label, "n_obs": len(part),
                     "mean_annual_pct": float(part.mean()) * conventions.periods_per_year * 100.0,
                     "sharpe": float(part.mean()) / sd * math.sqrt(conventions.periods_per_year)
                     if len(part) >= conventions.min_obs_ratio and sd > 0 else math.nan})
    return rows


# ---------------------------------------------------------------------------------------------
# Família
# ---------------------------------------------------------------------------------------------

def _joint_block(series: Sequence[np.ndarray], pairs: Sequence[tuple[np.ndarray, np.ndarray]], cfg: BootstrapConfig) -> float:
    """Comprimento médio do bloco comum: o maior automático entre as séries, seus desvios absolutos e as diferenças
    estratégia − referência (conservador), ou o fixo de `cfg`."""
    n = int(series[0].size)
    if cfg.block is not None:
        return float(min(cfg.block, max(1.0, n / 3.0)))
    lengths = [optimal_block_length(s) for s in series]
    lengths += [optimal_block_length(np.abs(s - s.mean())) for s in series]
    lengths += [optimal_block_length(a - b) for a, b in pairs]
    return float(min(max(max(lengths), cfg.min_block), max(1.0, n / 3.0)))


def _resampler(n: int, block: float, cfg: BootstrapConfig) -> Resampler:
    return Resampler(stationary_indices(n, cfg.n_boot, block, np.random.default_rng(cfg.seed)), block, cfg)


def evaluate_family(
    cases: Sequence[Case],
    benchmarks: Sequence[Benchmark],
    setup: ValidationSetup,
    descriptive: Sequence[Benchmark] = (),
    progress: Callable[[str], None] | None = None,
) -> ValidationReport:
    """Executa o protocolo inteiro para a família `cases` (ver docstring do módulo)."""
    say = progress or (lambda _msg: None)
    bench = {b.name: b for b in benchmarks}
    for c in cases:
        if c.benchmark not in bench:
            raise ValueError(f"{c.name}: referência {c.benchmark} não declarada")
        if c.cfg != bench[c.benchmark].cfg:
            raise ValueError(f"{c.name}: premissas de execução diferentes das da referência {c.benchmark}")

    # ---- simulações: referências (uma vez por cenário) e estratégias ----------------------------------
    bench_returns: dict[tuple[str, str], pd.Series] = {}
    for b in benchmarks:
        for scenario in ALL_SCENARIOS:
            say(f"referência {b.name} · {scenario}")
            bench_returns[(b.name, scenario)] = scenario_returns(setup, b.targets, b.cfg, scenario, f"{b.name}/{scenario}")
    base_results: dict[str, BacktestResult] = {}
    for b in [*benchmarks, *descriptive]:
        base_results[b.name] = simulate(setup.panel, b.targets, b.cfg, setup.start, setup.end, setup.eligible, b.name)
    case_returns: dict[tuple[str, str], pd.Series] = {}
    scenario_rows: list[dict[str, object]] = []
    variant_rows: list[dict[str, object]] = []
    fold_rows: list[dict[str, object]] = []
    regime_rows: list[dict[str, object]] = []
    for c in cases:
        if c.invalid_reason:
            continue
        base_results[c.name] = simulate(setup.panel, c.targets, c.cfg, setup.start, setup.end, setup.eligible, c.name)
        for scenario in ALL_SCENARIOS:
            say(f"{c.name} · {scenario}")
            r = base_results[c.name].returns if scenario == SCENARIO_BASE else scenario_returns(
                setup, c.targets, c.cfg, scenario, f"{c.name}/{scenario}")
            case_returns[(c.name, scenario)] = r
            br = bench_returns[(c.benchmark, scenario)]
            ms = return_metrics(r, None, setup.conventions)
            scenario_rows.append({
                "strategy": c.name, "benchmark": c.benchmark, "scenario": scenario, "stress": scenario in STRESS_SCENARIOS,
                "sharpe": ms["sharpe"], "benchmark_sharpe": _sharpe(br, setup.conventions),
                "delta_sharpe": _sharpe(r, setup.conventions) - _sharpe(br, setup.conventions),
                "cagr_pct": ms["cagr_pct"], "max_drawdown_pct": ms["max_drawdown_pct"],
            })
        for vname, vtargets in c.variants.items():
            say(f"{c.name} · variação {vname}")
            vr = simulate(setup.panel, vtargets, c.cfg, setup.start, setup.end, setup.eligible, f"{c.name}/{vname}").returns
            variant_rows.append({"strategy": c.name, "variant": vname,
                                 "sharpe": _sharpe(vr, setup.conventions),
                                 "delta_sharpe": _sharpe(vr, setup.conventions) - _sharpe(bench_returns[(c.benchmark, SCENARIO_BASE)], setup.conventions)})
        fold_rows += _fold_rows(c, base_results[c.name].returns, bench_returns[(c.benchmark, SCENARIO_BASE)], setup)
        regime_rows += _regime_rows(c.name, base_results[c.name].returns, setup.regimes, setup.conventions)
    for b in [*benchmarks, *descriptive]:
        regime_rows += _regime_rows(b.name, base_results[b.name].returns, setup.regimes, setup.conventions)

    # ---- bootstrap conjunto -----------------------------------------------------------------------
    valid = [c for c in cases if not c.invalid_reason]
    names = [c.name for c in valid]
    all_names = [*names, *[b.name for b in [*benchmarks, *descriptive]]]
    returns = pd.DataFrame({n: base_results[n].returns for n in all_names})
    if returns.isna().to_numpy().any():
        raise ValueError("séries fora da amostra desalinhadas (calendários diferentes)")
    arrays = {n: _floats(returns[n]) for n in all_names}
    pairs = [(arrays[c.name], arrays[c.benchmark]) for c in valid]
    block = _joint_block(list(arrays.values()), pairs, setup.boot)
    res = _resampler(len(returns), block, setup.boot)
    say(f"bootstrap: {setup.boot.n_boot} reamostras, bloco médio {block:.1f} dias")
    sharpe, cagr = sharpe_stat(setup.conventions.periods_per_year), cagr_stat(setup.conventions.periods_per_year)
    own_sharpe = {n: bootstrap_statistic(arrays[n], sharpe, res) for n in all_names}
    own_cagr = {n: bootstrap_statistic(arrays[n], cagr, res) for n in all_names}
    delta: dict[str, Estimate] = {c.name: bootstrap_difference(arrays[c.name], arrays[c.benchmark], sharpe, res) for c in valid}
    delta_cagr = {c.name: bootstrap_difference(arrays[c.name], arrays[c.benchmark], cagr, res) for c in valid}
    family = [c for c in cases if c.family_member]
    family_p = {c.name: (delta[c.name].p_value if c.name in delta else math.nan) for c in family}
    holm_table = holm(family_p, setup.criteria.alpha)
    holm_p = dict(zip(holm_table["hypothesis"].astype(str), holm_table["p_holm"].astype(float), strict=True))
    family_valid = [c.name for c in family if c.name in delta]
    maxstat = dict(zip(family_valid, max_stat_pvalues([delta[n] for n in family_valid]), strict=True))

    block_rows: list[dict[str, object]] = []
    for length in (block, *setup.block_sensitivity):
        alt = res if length == block else _resampler(len(returns), float(length), setup.boot)
        for c in valid:
            e = delta[c.name] if alt is res else bootstrap_difference(arrays[c.name], arrays[c.benchmark], sharpe, alt)
            block_rows.append({"strategy": c.name, "block": float(length), "automatic": length == block,
                               "ci_low": e.ci_low, "ci_high": e.ci_high, "p_value": e.p_value})

    # ---- resumo e classificação -------------------------------------------------------------------
    scen = pd.DataFrame(scenario_rows)
    variants = pd.DataFrame(variant_rows, columns=["strategy", "variant", "sharpe", "delta_sharpe"])
    folds_df = pd.DataFrame(fold_rows)
    summary_rows: list[dict[str, object]] = []
    for c in cases:
        row: dict[str, object] = {"strategy": c.name, "universe": c.universe, "benchmark": c.benchmark, "role": "ESTRATEGIA",
                                  "family_member": c.family_member, "timing": c.timing, "invalid_reason": c.invalid_reason or ""}
        if c.invalid_reason:
            category, reasons = classify(EvidenceInput(c.invalid_reason, 0, 0, c.timing, *([math.nan] * 10)), setup.criteria)
            summary_rows.append({**row, "p_holm": holm_p.get(c.name, math.nan),
                                 "category": category, "reasons": "; ".join(reasons)})
            continue
        m = engine_metrics(base_results[c.name], setup.conventions)
        mb = engine_metrics(base_results[c.benchmark], setup.conventions)
        d, dc = delta[c.name], delta_cagr[c.name]
        f = folds_df[folds_df["strategy"].eq(c.name)]
        fold_share = float(f["delta_sharpe"].gt(0).mean()) if f["delta_sharpe"].notna().any() else math.nan
        stress = scen[scen["strategy"].eq(c.name) & scen["stress"]]
        stress_min = float(stress["delta_sharpe"].min()) if stress["delta_sharpe"].notna().all() else math.nan
        worst = (str(stress["scenario"].astype(str).to_numpy()[int(np.nanargmin(stress["delta_sharpe"].to_numpy(dtype="float64")))])
                 if stress["delta_sharpe"].notna().any() else "")
        v = variants[variants["strategy"].eq(c.name)]
        v_share = float(v["delta_sharpe"].gt(0).mean()) if len(v) else math.nan
        p_holm = holm_p.get(c.name, math.nan)
        category, reasons = classify(EvidenceInput(
            None, int(_num(m["n_obs"])), int(_num(m["n_entries"])), c.timing, d.estimate, d.ci_low, d.ci_high, p_holm,
            fold_share, stress_min, v_share, _num(m["cagr_pct"]), _num(m["max_drawdown_pct"]), _num(mb["max_drawdown_pct"]),
        ), setup.criteria)
        summary_rows.append({
            **row, **{k: v_ for k, v_ in m.items()},
            "sharpe_ci_low": own_sharpe[c.name].ci_low, "sharpe_ci_high": own_sharpe[c.name].ci_high,
            "cagr_ci_low_pct": own_cagr[c.name].ci_low * 100.0, "cagr_ci_high_pct": own_cagr[c.name].ci_high * 100.0,
            "benchmark_sharpe": mb["sharpe"], "benchmark_cagr_pct": mb["cagr_pct"], "benchmark_max_drawdown_pct": mb["max_drawdown_pct"],
            "delta_sharpe": d.estimate, "delta_sharpe_ci_low": d.ci_low, "delta_sharpe_ci_high": d.ci_high,
            "p_value": d.p_value, "p_holm": p_holm, "p_maxstat": maxstat.get(c.name, math.nan),
            "delta_cagr_pct": dc.estimate * 100.0, "delta_cagr_ci_low_pct": dc.ci_low * 100.0, "delta_cagr_ci_high_pct": dc.ci_high * 100.0,
            "positive_fold_share": fold_share, "n_folds": len(f), "stress_min_delta_sharpe": stress_min, "stress_worst": worst,
            "variant_positive_share": v_share, "n_variants": len(v), "block": block, "n_boot": setup.boot.n_boot,
            "category": category, "reasons": "; ".join(reasons),
        })
    for b in [*benchmarks, *descriptive]:
        m = engine_metrics(base_results[b.name], setup.conventions)
        summary_rows.append({"strategy": b.name, "universe": b.universe, "benchmark": "", "role": "REFERENCIA",
                             "family_member": False, "timing": False, "invalid_reason": "", **m,
                             "sharpe_ci_low": own_sharpe[b.name].ci_low, "sharpe_ci_high": own_sharpe[b.name].ci_high,
                             "cagr_ci_low_pct": own_cagr[b.name].ci_low * 100.0, "cagr_ci_high_pct": own_cagr[b.name].ci_high * 100.0,
                             "block": block, "n_boot": setup.boot.n_boot, "category": "", "reasons": ""})
    return ValidationReport(
        summary=pd.DataFrame(summary_rows), folds=folds_df, scenarios=scen, variants=variants,
        blocks=pd.DataFrame(block_rows), regimes=pd.DataFrame(regime_rows), returns=returns, block=block,
    )


def _num(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float | np.integer | np.floating):
        return float(value)
    return math.nan
