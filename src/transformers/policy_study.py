"""Estudo completo da Fase 5 (sem I/O): protocolo -> tabela longa de resultados, com incerteza e Holm.

Puro (CLAUDE.md §1). Quem lê a base, consulta o Git, registra o experimento e grava Parquet é
`research/regime_policy_study.py`. O protocolo (docs/regime_policy.md) é fixado em `Protocol` antes da execução.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

import pandas as pd

from .. import config
from .policy_evaluation import (
    BOOTSTRAP_RESAMPLES,
    DAYS_PER_YEAR,
    PRIMARY_BLOCK,
    SharpeComparison,
    holm_adjust,
    metrics,
    paired_sharpe_bootstrap,
    slice_window,
)
from .policy_experiment import Scenario, ScenarioResult, run_scenario
from .regime_policy import FIXED_POLICIES, LEARNABLE, MIN_TRAIN_DAYS, POLICY_LEARNED, POLICY_PRIMARY, POLICY_VERSION
from .regimes import CLASSIFIER_VERSION, RegimeRules, classify_market_regimes
from .selection import compute_features
from .selection_backtest import STRATEGY_BTC, STRATEGY_HOLD_ALL, STRATEGY_MOMENTUM, STRATEGY_SMA200
from .strategies import market_from_candles

PRIMARY_REFERENCE = STRATEGY_SMA200
FAMILY_BASELINES: tuple[str, ...] = (STRATEGY_HOLD_ALL, STRATEGY_SMA200, STRATEGY_MOMENTUM, STRATEGY_BTC)
POLICY_NAMES: tuple[str, ...] = (*FIXED_POLICIES, POLICY_LEARNED)
RESULT_SCHEMA: dict[str, str] = {
    "section": "string", "scenario": "string", "window": "string", "key": "string", "metric": "string",
    "value": "float64", "note": "string",
}

DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("base"),
    Scenario("custo x0,5", cost_scale=0.5),
    Scenario("custo x2", cost_scale=2.0),
    Scenario("atraso 1 dia", lag_days=1),
    Scenario("rebalanceamento 14 dias", every=14),
    Scenario("universo BTC+ETH", universe=config.RECOMMENDED),
    Scenario("regime indisponivel 10%", regime_dropout=0.10),
    Scenario("sem faixa de tolerancia", band=0.0),
)
DEFAULT_CLASSIFIERS: tuple[tuple[str, RegimeRules], ...] = (
    ("classificador media 150", RegimeRules(ma_window=150)),
    ("classificador media 250", RegimeRules(ma_window=250)),
    ("classificador confirmacao 3", RegimeRules(confirm_days=3)),
    ("classificador confirmacao 7", RegimeRules(confirm_days=7)),
)


@dataclass(frozen=True)
class Protocol:
    """Parâmetros do estudo, fixados antes da execução (docs/regime_policy.md)."""

    primary_start: str = "2021-01-01"
    seed: int = 20261016
    block: int = PRIMARY_BLOCK
    resamples: int = BOOTSTRAP_RESAMPLES
    sensitivity_blocks: tuple[int, ...] = (10, 40)
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS
    classifiers: tuple[tuple[str, RegimeRules], ...] = DEFAULT_CLASSIFIERS
    include_selection: bool = True

    def describe(self) -> dict[str, object]:
        """Configuração serializável (entra no ID do experimento)."""
        return {
            "protocol_revision": 2, "primary_start": self.primary_start, "seed": self.seed, "block": self.block, "resamples": self.resamples,
            "sensitivity_blocks": list(self.sensitivity_blocks), "include_selection": self.include_selection,
            "scenarios": [asdict(s) for s in self.scenarios],
            "classifiers": {name: asdict(rules) for name, rules in self.classifiers},
            "policies": {name: p.fingerprint() for name, p in FIXED_POLICIES.items()},
            "learned": {"min_train_days": MIN_TRAIN_DAYS, "candidates": list(LEARNABLE)},
            "policy_version": POLICY_VERSION, "classifier_version": CLASSIFIER_VERSION,
            "costs": {"fee_per_side": config.FEE_PER_SIDE, "slippage": config.SLIPPAGE, "spread_tiers": config.SPREAD_TIERS,
                      "rebalance_band": config.REBALANCE_BAND},
            "reference": PRIMARY_REFERENCE, "baselines": list(FAMILY_BASELINES),
            "periods": {"validacao": list(config.VALIDATION_PERIOD), "teste": list(config.TEST_PERIOD)},
        }


@dataclass(frozen=True)
class StudyResults:
    results: pd.DataFrame
    decisions: pd.DataFrame
    mappings: pd.DataFrame
    config: Mapping[str, object]
    n_policies: int
    n_variants: int
    n_hypotheses: int
    period: tuple[pd.Timestamp, pd.Timestamp]


def _row(section: str, scenario: str, window: str, key: str, metric: str, value: float, note: str = "") -> dict[str, object]:
    return {"section": section, "scenario": scenario, "window": window, "key": key, "metric": metric, "value": float(value), "note": note}


def windows_for(start: pd.Timestamp, end: pd.Timestamp) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Janela primária, cada ano civil, VALIDACAO e TESTE (períodos do config), todos dentro de [start, end]."""
    out = {"PRIMARIA": (start, end)}
    for year in range(start.year, end.year + 1):
        out[str(year)] = (max(start, pd.Timestamp(f"{year}-01-01", tz="UTC")), min(end, pd.Timestamp(f"{year}-12-31", tz="UTC")))
    out["VALIDACAO"] = (max(start, pd.Timestamp(config.VALIDATION_PERIOD[0], tz="UTC")), min(end, pd.Timestamp(config.VALIDATION_PERIOD[1], tz="UTC")))
    out["TESTE"] = (max(start, pd.Timestamp(config.TEST_PERIOD[0], tz="UTC")), end)
    return out


def _scenario_rows(result: ScenarioResult, windows: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    name = result.scenario.name
    primary = windows["PRIMARIA"]
    for strategy, run in result.runs.items():
        for window, span in windows.items():
            daily, exposure = slice_window(run.daily, span), slice_window(run.exposure, span)
            for metric, value in metrics(daily, exposure).items():
                rows.append(_row("metricas", name, window, strategy, metric, value))
        years = max(len(slice_window(run.daily, primary)) / DAYS_PER_YEAR, 1e-9)
        rows += [
            _row("custos", name, "PRIMARIA", strategy, "turnover_por_ano", run.turnover / years, "soma de |mudança de peso| por ano"),
            _row("custos", name, "PRIMARIA", strategy, "custo_total_pct", run.cost * 100.0, "% do capital, somado no período"),
            _row("custos", name, "PRIMARIA", strategy, "entradas", float(run.n_trades), "entradas em moedas (de 0 para > 0)"),
        ]
    rows += [_row("trocas", name, "PRIMARIA", policy, "trocas_de_estrategia", float(n)) for policy, n in result.switches.items()]
    return rows


def run_study(candles: pd.DataFrame, as_of: pd.Timestamp, protocol: Protocol = Protocol()) -> StudyResults:
    """Executa o protocolo inteiro sobre candles já limpos. Determinístico (semente do protocolo)."""
    market = candles[["symbol", "timestamp", "high", "low", "close", "quote_volume"]]
    features = compute_features(market_from_candles(market))
    ref = market[market["symbol"].eq(config.REGIME_SYMBOL)]
    btc = pd.Series(ref["close"].to_numpy(dtype="float64"), index=pd.DatetimeIndex(ref["timestamp"]))
    start = pd.Timestamp(protocol.primary_start, tz="UTC")
    end = pd.Timestamp(features.index.get_level_values("timestamp").max())
    windows = windows_for(start, end)
    base_regime = classify_market_regimes(btc, as_of, RegimeRules())

    results: dict[str, ScenarioResult] = {}
    for scenario in protocol.scenarios:
        results[scenario.name] = run_scenario(
            features, base_regime, scenario, start, end, protocol.seed,
            include_selection=protocol.include_selection and scenario.name == "base",
        )
    for label, rules in protocol.classifiers:
        results[label] = run_scenario(features, classify_market_regimes(btc, as_of, rules), Scenario(label), start, end, protocol.seed)
    rows: list[dict[str, object]] = []
    for result in results.values():
        rows += _scenario_rows(result, windows)

    # Inferência: só no cenário-base e na janela primária (família de políticas × baselines).
    base = results["base"]
    primary = windows["PRIMARIA"]
    comparisons: list[tuple[str, str, SharpeComparison]] = []
    for policy in POLICY_NAMES:
        for baseline in FAMILY_BASELINES:
            comparisons.append((policy, baseline, paired_sharpe_bootstrap(
                slice_window(base.runs[policy].daily, primary), slice_window(base.runs[baseline].daily, primary),
                protocol.block, protocol.resamples, protocol.seed)))
    adjusted = holm_adjust([c.p_value for _, _, c in comparisons])
    for (policy, baseline, comp), p_holm in zip(comparisons, adjusted, strict=True):
        note = "PRIMARIA (pré-registrada)" if (policy, baseline) == (POLICY_PRIMARY, PRIMARY_REFERENCE) else "família de 20 hipóteses"
        key = f"{policy} vs {baseline}"
        rows += [_row("comparacao", "base", "PRIMARIA", key, metric, value, note) for metric, value in comp.row().items()]
        rows.append(_row("comparacao", "base", "PRIMARIA", key, "p_holm", p_holm, note))
    for block in protocol.sensitivity_blocks:
        for policy in POLICY_NAMES:
            comp = paired_sharpe_bootstrap(slice_window(base.runs[policy].daily, primary),
                                           slice_window(base.runs[PRIMARY_REFERENCE].daily, primary),
                                           block, protocol.resamples, protocol.seed)
            rows += [_row("sensibilidade_bloco", "base", "PRIMARIA", f"{policy} vs {PRIMARY_REFERENCE}", metric, value, f"bloco {block}")
                     for metric, value in comp.row().items() if metric in ("diff", "ci_low", "ci_high", "p_value")]
    # Robustez: diferença de Sharpe de cada política contra a referência primária em cada variante (estimativa pontual).
    for name, result in results.items():
        ref_sharpe = metrics(slice_window(result.runs[PRIMARY_REFERENCE].daily, primary))["sharpe"]
        for policy in POLICY_NAMES:
            own = metrics(slice_window(result.runs[policy].daily, primary))["sharpe"]
            rows.append(_row("robustez", name, "PRIMARIA", f"{policy} vs {PRIMARY_REFERENCE}", "diff_sharpe", own - ref_sharpe,
                             "estimativa pontual, sem intervalo"))

    # Suplementar (revisão 2, ver docs/regime_policy.md): IC da comparação primária em TODAS as variantes, sem escolher
    # nenhuma. Fora da família de 20 hipóteses, sem ajuste; serve só para ver se a leitura muda com a variante.
    for name, result in results.items():
        comp = paired_sharpe_bootstrap(slice_window(result.runs[POLICY_PRIMARY].daily, primary),
                                       slice_window(result.runs[PRIMARY_REFERENCE].daily, primary),
                                       protocol.block, protocol.resamples, protocol.seed)
        rows += [_row("robustez_ic", name, "PRIMARIA", f"{POLICY_PRIMARY} vs {PRIMARY_REFERENCE}", metric, value,
                      "suplementar: fora da família, sem ajuste")
                 for metric, value in comp.row().items() if metric in ("diff", "ci_low", "ci_high", "p_value")]

    out = pd.DataFrame(rows, columns=list(RESULT_SCHEMA)).astype(RESULT_SCHEMA)
    return StudyResults(out, base.decisions, base.mappings, protocol.describe(), len(POLICY_NAMES), len(results),
                        len(comparisons), (start, end))
