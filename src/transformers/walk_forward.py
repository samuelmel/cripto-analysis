"""Protocolo temporal walk-forward: janelas de treino, validação e teste, escolha de parâmetros sem ver o teste.

Puro (CLAUDE.md §1).

Janelas (`WalkForwardPlan` -> `make_folds`), em dias de calendário UTC:
    treino      [data_start, train_end]: tudo o que existe até a data da escolha (janela ANCORADA, que cresce),
                inclusive o aquecimento dos indicadores (SMA 200 precisa de 200 dias; o universo point-in-time, de
                365 candles próprios por moeda).
    validação   [train_end − validation_days + 1, train_end]: parte final do treino onde os candidatos de
                parâmetro são comparados (o mesmo papel da validação 2021–2022 do laboratório antigo).
    embargo     `embargo_days` entre train_end e test_start. Padrão 0: as métricas são diárias e marcadas a
                mercado (não há rótulo que se estenda para o futuro, como o retorno de uma operação de N dias), o
                treino nunca inclui o retorno de test_start e a ordem decidida no fechamento de train_end só é
                executada na abertura de test_start, dentro do teste. Com rótulos de horizonte h, use h − 1.
    teste       [test_start, test_end]: `step_months` meses; só mede.

Parâmetros no teste: a decisão do dia D usa o candidato escolhido na dobra k mais recente com train_end <= D
(conhecido no fechamento de D). Antes da primeira escolha não há parâmetro, e o alvo é caixa. Assim o teste de uma
dobra nunca entra na escolha dela (`select_per_fold` só entrega ao avaliador alvos até train_end, e o motor só
usa preços até o fim da janela pedida).

Status dos dados (`data_status`): um período de teste anterior a `explored_until` já foi visto durante o
desenvolvimento das regras (é o caso de TODO o histórico disponível até a Fase 3): o walk-forward garante que a
ESCOLHA DE PARÂMETROS da grade não viu o teste, mas não que as regras em si não foram desenhadas olhando esses anos.
Só dado posterior a `explored_until` é prospectivo.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

STATUS_EXPLORED = "EXPLORADO_NO_DESENVOLVIMENTO"
STATUS_PROSPECTIVE = "PROSPECTIVO"


class HoldoutViolation(ValueError):
    """Uma janela de escolha encostou no período que ela deveria só medir."""


@dataclass(frozen=True)
class Fold:
    index: int
    label: str
    train_start: pd.Timestamp
    validation_start: pd.Timestamp
    train_end: pd.Timestamp       # data da escolha: último fechamento conhecido
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    data_status: str


@dataclass(frozen=True)
class WalkForwardPlan:
    data_start: pd.Timestamp
    first_test: pd.Timestamp
    last_day: pd.Timestamp
    explored_until: pd.Timestamp     # último dia que o desenvolvimento já consultou
    step_months: int = 12
    validation_days: int = 730
    min_train_days: int = 730
    embargo_days: int = 0

    def __post_init__(self) -> None:
        if self.step_months < 1 or self.validation_days < 30 or self.min_train_days < self.validation_days:
            raise ValueError("step_months >= 1, validation_days >= 30, min_train_days >= validation_days")
        if self.embargo_days < 0:
            raise ValueError("embargo_days >= 0")
        if not self.data_start < self.first_test <= self.last_day:
            raise ValueError("precisa data_start < first_test <= last_day")


def make_folds(plan: WalkForwardPlan) -> tuple[Fold, ...]:
    """Dobras consecutivas de teste de `step_months` meses a partir de `first_test` até `last_day`."""
    one = pd.Timedelta(days=1)
    starts: list[pd.Timestamp] = []
    start = plan.first_test
    while start <= plan.last_day:
        starts.append(start)
        start = start + pd.DateOffset(months=plan.step_months)
    folds: list[Fold] = []
    for i, test_start in enumerate(starts):
        test_end = min(starts[i + 1] - one, plan.last_day) if i + 1 < len(starts) else plan.last_day
        train_end = test_start - one - pd.Timedelta(days=plan.embargo_days)
        if (train_end - plan.data_start).days + 1 < plan.min_train_days:
            raise HoldoutViolation(f"dobra {i}: treino com menos de {plan.min_train_days} dias")
        validation_start = max(plan.data_start, train_end - pd.Timedelta(days=plan.validation_days - 1))
        status = STATUS_EXPLORED if test_start <= plan.explored_until else STATUS_PROSPECTIVE
        label = f"{test_start:%Y-%m}" if plan.step_months < 12 else f"{test_start:%Y}"
        folds.append(Fold(i, label, plan.data_start, validation_start, train_end, test_start, test_end, status))
    check_folds(folds)
    return tuple(folds)


def check_folds(folds: tuple[Fold, ...] | list[Fold]) -> None:
    """Falha (HoldoutViolation) se alguma escolha puder ter visto o próprio teste ou se os testes se sobrepõem."""
    for f in folds:
        if not f.train_start <= f.validation_start <= f.train_end < f.test_start <= f.test_end:
            raise HoldoutViolation(f"dobra {f.index}: precisa treino <= validação <= escolha < teste")
    for a, b in zip(folds, folds[1:], strict=False):
        if b.test_start <= a.test_end:
            raise HoldoutViolation(f"dobras {a.index} e {b.index}: testes sobrepostos")


def assign_decisions(days: pd.DatetimeIndex, folds: tuple[Fold, ...]) -> np.ndarray:
    """Para cada dia de decisão, a dobra cujo parâmetro vale (a mais recente com train_end <= dia); −1 = nenhuma."""
    ends = np.array([f.train_end.value for f in folds], dtype=np.int64)
    when = np.array([pd.Timestamp(d).value for d in days], dtype=np.int64)
    pos = np.searchsorted(ends, when, side="right") - 1
    return np.asarray(pos, dtype=np.int64)


SELECTION_SCHEMA: dict[str, str] = {
    "fold": "Int64",
    "fold_label": "string",
    "candidate": "string",
    "score": "float64",       # métrica de escolha na validação da dobra
    "eligible": "bool",       # passou na condição mínima (ex.: número de operações)
    "chosen": "bool",
    "validation_start": "datetime64[ns, UTC]",
    "train_end": "datetime64[ns, UTC]",
    "n_candidates": "Int64",
}

ScoreFn = Callable[[pd.DataFrame, pd.Timestamp, pd.Timestamp], tuple[float, bool]]


def select_per_fold(candidates: Mapping[str, pd.DataFrame], folds: tuple[Fold, ...], score: ScoreFn) -> pd.DataFrame:
    """Avalia cada candidato na validação de cada dobra e marca o escolhido (maior score entre os elegíveis; empate
    = o primeiro na ordem dada). O avaliador recebe só as decisões até `train_end`: nada do teste."""
    check_folds(folds)
    rows: list[dict[str, object]] = []
    for f in folds:
        scored: list[tuple[str, float, bool]] = []
        for name, targets in candidates.items():
            value, ok = score(targets.loc[: f.train_end], f.validation_start, f.train_end)
            scored.append((name, float(value), bool(ok) and bool(np.isfinite(value))))
        valid = [(n, v) for n, v, ok in scored if ok]
        best = max(valid, key=lambda t: t[1])[0] if valid else None
        for name, value, ok in scored:
            rows.append({"fold": f.index, "fold_label": f.label, "candidate": name, "score": value, "eligible": ok,
                         "chosen": name == best, "validation_start": f.validation_start, "train_end": f.train_end,
                         "n_candidates": len(candidates)})
    return pd.DataFrame(rows)[list(SELECTION_SCHEMA)].astype(SELECTION_SCHEMA)


def stitch_targets(candidates: Mapping[str, pd.DataFrame], selection: pd.DataFrame, folds: tuple[Fold, ...]) -> pd.DataFrame:
    """Alvos fora da amostra: cada decisão usa o candidato escolhido na dobra vigente; sem escolha = caixa (0)."""
    frames = list(candidates.values())
    index = frames[0].index
    columns = frames[0].columns
    picked = selection[selection["chosen"]]
    chosen = {int(f): str(c) for f, c in zip(picked["fold"].astype("int64").tolist(), picked["candidate"].astype(str), strict=True)}
    owner = assign_decisions(pd.DatetimeIndex(index), folds)
    out = pd.DataFrame(0.0, index=index, columns=columns)
    for k in range(len(folds)):
        rows = owner == k
        if k in chosen and rows.any():
            out.loc[rows] = candidates[chosen[k]].reindex(index=index, columns=columns).fillna(0.0).loc[rows].to_numpy()
    return out


def delay_targets(targets: pd.DataFrame, days: int) -> pd.DataFrame:
    """Os mesmos alvos decididos `days` dias depois (sensibilidade a atraso de execução)."""
    if days < 0:
        raise ValueError("atraso >= 0")
    return targets.set_axis(targets.index + pd.Timedelta(days=days), axis=0)


def fold_of_days(days: pd.DatetimeIndex, folds: tuple[Fold, ...]) -> pd.Series:
    """Rótulo da dobra de teste de cada dia (vazio fora de todos os testes)."""
    labels = pd.Series(pd.NA, index=days, dtype="string")
    for f in folds:
        labels[(days >= f.test_start) & (days <= f.test_end)] = f.label
    return labels
