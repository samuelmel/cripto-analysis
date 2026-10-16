"""Políticas que escolhem a estratégia pelo regime de mercado (Fase 5, pesquisa). Isoladas da produção.

Puro (CLAUDE.md §1). Nada aqui é importado por `pipeline.py`, `selection.py`, `allocation.py` nem pelo painel: uma
política só produz PESOS-ALVO por dia de rebalanceamento para o motor de pesquisa (`selection_backtest.run_weighted`).
Não executa ordens.

Contrato temporal
    A decisão do dia `d` (fechamento de `d`) usa a linha de regime de `d`, conhecida em `known_at = d + 1 dia`, isto é,
    no próprio fechamento. `policy_targets` recusa (ValueError) uma linha cujo `known_at` seja posterior ao fechamento
    de `d`. O peso vale a partir do retorno de `d + 1` (motor existente: execução no fechamento de `d`).

Estados sem classificação (`MISTO`, `LATERAL`, `BAIXA`, `INDETERMINADO`, `INDISPONIVEL`) nunca são promovidos a `ALTA`
ou `BAIXA`: o que a tabela não lista vai para `CAIXA`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .regimes import TREND_REGIMES, TREND_STATES, UNAVAILABLE, VOL_REGIMES
from .selection_backtest import STRATEGY_HOLD_ALL, STRATEGY_MOMENTUM, STRATEGY_SMA200

POLICY_VERSION = "regime-policy-1.0.0"
"""Muda quando uma tabela, a regra de escolha ou o significado de um estado muda (nunca em silêncio)."""

CASH = "CAIXA"
ANY = "*"
CANDIDATES: tuple[str, ...] = (STRATEGY_HOLD_ALL, STRATEGY_SMA200, STRATEGY_MOMENTUM, CASH)
LEARNABLE: tuple[str, ...] = (STRATEGY_HOLD_ALL, STRATEGY_SMA200, STRATEGY_MOMENTUM)

MIN_TRAIN_DAYS = 180
"""P5: dias de treino num estado de tendência abaixo disso -> CAIXA (amostra insuficiente), fixado a priori."""

POLICY_PRIMARY = "P1_DEFENSIVA"
POLICY_MOMENTUM_UP = "P2_MOMENTO_NA_ALTA"
POLICY_VOL_FILTERED = "P3_VOL_FILTRADA"
POLICY_HOLD_UP = "P4_ALTA_SEGURAR"
POLICY_LEARNED = "P5_APRENDIDA_WF"

DECISION_SCHEMA: dict[str, str] = {
    "policy": "string", "day": "datetime64[ns, UTC]", "known_at": "datetime64[ns, UTC]",
    "trend_regime": "string", "vol_regime": "string", "strategy": "string", "switched": "bool",
}
MAPPING_SCHEMA: dict[str, str] = {"year": "int64", "trend_regime": "string", "strategy": "string", "train_days": "int64"}


@dataclass(frozen=True)
class RegimePolicy:
    """Tabela (tendência, volatilidade) -> estratégia. A primeira linha que casa vale; `default` cobre o resto."""

    name: str
    rows: tuple[tuple[str, str, str], ...]
    default: str = CASH
    version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        for trend, vol, strategy in self.rows:
            if trend != ANY and trend not in TREND_REGIMES:
                raise ValueError(f"{self.name}: regime de tendência desconhecido {trend!r}")
            if vol != ANY and vol not in VOL_REGIMES:
                raise ValueError(f"{self.name}: regime de volatilidade desconhecido {vol!r}")
            if strategy not in CANDIDATES:
                raise ValueError(f"{self.name}: estratégia desconhecida {strategy!r}")
        if self.default not in CANDIDATES:
            raise ValueError(f"{self.name}: estratégia padrão desconhecida {self.default!r}")

    def choose(self, trend: str, vol: str) -> str:
        for t, v, strategy in self.rows:
            if t in (ANY, trend) and v in (ANY, vol):
                return strategy
        return self.default

    def fingerprint(self) -> str:
        payload = json.dumps({"name": self.name, "version": self.version, "rows": self.rows, "default": self.default})
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


FIXED_POLICIES: dict[str, RegimePolicy] = {
    p.name: p for p in (
        RegimePolicy(POLICY_PRIMARY, (("ALTA", ANY, STRATEGY_SMA200),)),
        RegimePolicy(POLICY_MOMENTUM_UP, (("ALTA", ANY, STRATEGY_MOMENTUM), ("MISTO", ANY, STRATEGY_SMA200))),
        RegimePolicy(POLICY_VOL_FILTERED, (("ALTA", "NORMAL", STRATEGY_SMA200),)),
        RegimePolicy(POLICY_HOLD_UP, (("ALTA", ANY, STRATEGY_HOLD_ALL),)),
    )
}

Chooser = Callable[[pd.Timestamp, str, str], str]
"""(dia de decisão, regime de tendência, regime de volatilidade) -> nome da estratégia."""


def fixed_chooser(policy: RegimePolicy) -> Chooser:
    return lambda day, trend, vol: policy.choose(trend, vol)


# ---------------------------------------------------------------------------------------------
# Alvos de uma política
# ---------------------------------------------------------------------------------------------

def policy_targets(
    chooser: Chooser,
    policy_name: str,
    candidate_targets: Mapping[str, pd.DataFrame],
    regime: pd.DataFrame,
    days: Sequence[pd.Timestamp],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pesos-alvo da política em cada dia de `days` e o histórico de decisões (DECISION_SCHEMA).

    `regime`: tabela de `classify_market_regimes` (usa timestamp, known_at, trend_regime, vol_regime). Dia sem linha
    de regime = INDISPONIVEL. `candidate_targets[nome]`: pesos de cada candidata nos mesmos dias e colunas.
    """
    reference = next(iter(candidate_targets.values()))
    idx = pd.DatetimeIndex(list(days))
    weights = pd.DataFrame(0.0, index=idx, columns=reference.columns)
    info = {
        pd.Timestamp(t): (str(a), str(b), pd.Timestamp(k))
        for t, a, b, k in zip(regime["timestamp"], regime["trend_regime"], regime["vol_regime"], regime["known_at"], strict=True)
    }
    rows: list[dict[str, object]] = []
    previous: str | None = None
    for day in idx:
        known: pd.Timestamp | None = None
        trend, vol = UNAVAILABLE, UNAVAILABLE
        if day in info:
            trend, vol, known = info[day]
            if known > day + pd.Timedelta(days=1):
                raise ValueError(f"regime de {day:%Y-%m-%d} só é conhecido em {known}, depois do fechamento da decisão")
        strategy = chooser(day, trend, vol)
        if strategy not in CANDIDATES:
            raise ValueError(f"{policy_name}: estratégia desconhecida {strategy!r}")
        if strategy != CASH:
            weights.loc[day] = candidate_targets[strategy].loc[day].to_numpy(dtype="float64")
        rows.append({"policy": policy_name, "day": day, "known_at": known, "trend_regime": trend, "vol_regime": vol,
                     "strategy": strategy, "switched": previous is not None and strategy != previous})
        previous = strategy
    decisions = pd.DataFrame(rows, columns=list(DECISION_SCHEMA))
    return weights, decisions.astype(DECISION_SCHEMA)


# ---------------------------------------------------------------------------------------------
# P5: mapeamento aprendido só com o passado (walk-forward anual, janela expansiva)
# ---------------------------------------------------------------------------------------------

def fit_mapping(
    candidate_returns: pd.DataFrame,
    trend_before: pd.Series,
    train_end: pd.Timestamp,
    min_days: int = MIN_TRAIN_DAYS,
) -> tuple[dict[str, str], dict[str, int]]:
    """Estado de tendência -> melhor candidata, usando SÓ retornos de dias anteriores a `train_end` (exclusivo).

    `candidate_returns`: retornos diários líquidos de cada candidata (colunas = LEARNABLE). `trend_before`: regime de
    tendência conhecido no fechamento do dia ANTERIOR ao do retorno (o retorno de `t` pertence ao regime de `t − 1`).
    Escolhe o maior Sharpe diário; exige `min_days` dias no estado e Sharpe > 0, senão CAIXA (que rende zero).
    Devolve também os dias de treino por estado.
    """
    past = candidate_returns[candidate_returns.index < train_end]
    labels = trend_before.reindex(past.index)
    mapping: dict[str, str] = {}
    days: dict[str, int] = {}
    for state in TREND_STATES:
        sample = past[labels.eq(state)].dropna()
        days[state] = len(sample)
        mapping[state] = CASH
        if len(sample) < min_days:
            continue
        sd = sample.std(ddof=1)
        sharpe = (sample.mean() / sd.where(sd > 0)).dropna()
        if not sharpe.empty and float(sharpe.max()) > 0:
            mapping[state] = str(sharpe.idxmax())
    return mapping, days


def learned_chooser(
    candidate_returns: pd.DataFrame, trend_before: pd.Series, min_days: int = MIN_TRAIN_DAYS
) -> tuple[Chooser, Callable[[], pd.DataFrame]]:
    """Escolhedor de P5 (reajusta no início de cada ano civil) e uma função que devolve as tabelas usadas."""
    cache: dict[int, tuple[dict[str, str], dict[str, int]]] = {}

    def table_for(year: int) -> tuple[dict[str, str], dict[str, int]]:
        if year not in cache:
            cache[year] = fit_mapping(candidate_returns, trend_before, pd.Timestamp(f"{year}-01-01", tz="UTC"), min_days)
        return cache[year]

    def choose(day: pd.Timestamp, trend: str, vol: str) -> str:
        return table_for(day.year)[0].get(trend, CASH)

    def mappings() -> pd.DataFrame:
        rows = [{"year": y, "trend_regime": s, "strategy": m[s], "train_days": d[s]}
                for y, (m, d) in sorted(cache.items()) for s in TREND_STATES]
        return pd.DataFrame(rows, columns=list(MAPPING_SCHEMA)).astype(MAPPING_SCHEMA)

    return choose, mappings


def count_switches(decisions: pd.DataFrame) -> int:
    return int(decisions["switched"].sum()) if not decisions.empty else 0


def random_dropout(regime: pd.DataFrame, fraction: float, seed: int) -> pd.DataFrame:
    """Teste de falha de dados: `fraction` dos dias passa a INDISPONIVEL (sorteio com semente fixa)."""
    if fraction <= 0:
        return regime
    out = regime.copy()
    hit = np.random.default_rng(seed).random(len(out)) < fraction
    out.loc[hit, "trend_regime"] = UNAVAILABLE
    out.loc[hit, "vol_regime"] = UNAVAILABLE
    return out
