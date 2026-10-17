"""Validação estatística do sinal COMPRAR, por moeda (regras em docs/signal_validation.md, fixadas antes dos resultados).

Puro (CLAUDE.md §1): recebe candles (DataFrame) e parâmetros, devolve DataFrames; nenhuma leitura de arquivo, rede ou
relógio. A semente é derivada de `config.VALIDATION_SEED`, da moeda e do horizonte: mesma entrada, mesma saída.

Pergunta: depois de um sinal COMPRAR (início de um episódio de alta: moeda e BTC acima da SMA 200), o retorno líquido
em `h` dias, com entrada no fechamento SEGUINTE ao sinal e custos de `config.py`, supera o de entrar em um dia
qualquer da mesma moeda (referência aleatória)?

Etapas: `prepare` (quadros largos, eventos e retornos futuros) -> `count_independent` (só contagens, sem retorno) ->
`evaluate_development` (estatística, Holm, status) -> `apply_holdout` (teste final: só pode revogar).
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config
from .selection import SelectionRules, cost_per_side
from .stats import block_indices, holm_adjust
from .universe_pit import PitRules, membership

STATUS_VALIDATED = "VALIDADA"
STATUS_NOT_VALIDATED = "NAO_VALIDADA"
STATUS_NO_EVIDENCE = "SEM_EVIDENCIA"
STATUS_REVOKED = "REVOGADA"
STATUS_NOT_ASSESSED = "NAO_AVALIADA"

HOLDOUT_CONFIRMED = "CONFIRMADA"
HOLDOUT_INSUFFICIENT = "INSUFICIENTE"
HOLDOUT_REFUTED = "REFUTADA"
HOLDOUT_NA = "NAO_APLICA"

SMA_WINDOW = 200
REGIME_SYMBOL = config.REGIME_SYMBOL

DETAIL_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "horizon": "int64",
    "period": "string",          # DESENVOLVIMENTO | TESTE_FINAL
    "n_events": "int64",         # sinais (inclusive sobrepostos) com janela completa
    "n_independent": "int64",
    "mean_signal": "float64",    # média do retorno líquido dos sinais independentes
    "mean_baseline": "float64",  # média do retorno líquido de entrar em qualquer dia elegível
    "excess": "float64",
    "ci_low": "float64",
    "ci_high": "float64",
    "p_value": "float64",
    "p_holm": "float64",
    "stable_halves": "bool",
    "in_family": "bool",
}

EVIDENCE_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "status": "string",
    "holdout": "string",
    "n_independent_7": "Int64",
    "n_independent_30": "Int64",
    "excess_7": "float64",
    "excess_30": "float64",
    "ci_low_7": "float64",
    "ci_low_30": "float64",
    "p_holm_7": "float64",
    "p_holm_30": "float64",
    "holdout_n_7": "Int64",
    "holdout_n_30": "Int64",
    "holdout_excess_7": "float64",
    "holdout_excess_30": "float64",
    "reason": "string",
}


@dataclass(frozen=True)
class ValidationRules:
    horizons: tuple[int, ...] = config.VALIDATION_HORIZONS
    development_end: str = config.DEVELOPMENT_END
    holdout_start: str = config.HOLDOUT_START
    alpha: float = config.VALIDATION_ALPHA
    seed: int = config.VALIDATION_SEED
    null_draws: int = config.VALIDATION_NULL_DRAWS
    resamples: int = config.VALIDATION_BOOTSTRAP_RESAMPLES
    holdout_min_signals: int = config.HOLDOUT_MIN_SIGNALS
    n_min: int = getattr(config, "VALIDATION_MIN_INDEPENDENT", 0)
    pit: PitRules = field(default_factory=PitRules)
    delisted_after_days: int = config.LONG_STALE_DAYS

    @property
    def dev_end(self) -> pd.Timestamp:
        return pd.Timestamp(self.development_end, tz="UTC")

    @property
    def hold_start(self) -> pd.Timestamp:
        return pd.Timestamp(self.holdout_start, tz="UTC")


@dataclass(frozen=True)
class Prepared:
    """Quadros largos (índice = dia, colunas = moedas) prontos para a estatística."""

    events: pd.DataFrame                  # True no primeiro dia de um episódio de alta, com a moeda no universo
    eligible: pd.DataFrame                # dia elegível para a referência aleatória (no universo, SMA 200 existe)
    forward: dict[int, pd.DataFrame]      # horizonte -> retorno líquido de entrar em t+1 e sair em t+1+h
    priced: pd.DataFrame | None = None    # fechamentos (deslistada: último preço adiante), para simular saídas
    sma: pd.DataFrame | None = None       # SMA 200 de cada moeda
    cost: pd.DataFrame | None = None      # custo por lado (taxa + spread + slippage)
    last_candle: pd.Series | None = None  # último dia com candle de cada moeda


def stable_seed(base: int, *parts: object) -> int:
    """Semente estável (não depende do `hash` aleatório do Python) derivada de `base` e de `parts`."""
    return (base + zlib.crc32("|".join(str(p) for p in parts).encode("utf-8"))) % (2**32)


def _sma(close: pd.DataFrame, window: int) -> pd.DataFrame:
    """SMA sobre os candles de cada moeda (dias sem candle não contam), alinhada ao calendário diário."""
    out = {}
    for symbol in close.columns:
        col = close[symbol].dropna()
        out[symbol] = col.rolling(window).mean().reindex(close.index)
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def prepare(candles: pd.DataFrame, rules: ValidationRules = ValidationRules()) -> Prepared:
    """Eventos de COMPRAR, dias elegíveis e retornos futuros líquidos de todas as moedas (usa só o passado em cada
    decisão; o futuro entra apenas no retorno medido depois da entrada)."""
    if candles.empty:
        raise ValueError("candles vazios")
    close = candles.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    days = pd.date_range(close.index.min(), close.index.max(), freq="D", tz="UTC")
    close = close.reindex(days)
    vol = candles.pivot(index="timestamp", columns="symbol", values="quote_volume").sort_index().reindex(days)
    member = membership(candles, rules.pit).reindex(index=days, columns=close.columns).fillna(False).astype(bool)

    sma = _sma(close, SMA_WINDOW)
    above = close.gt(sma)
    btc_up = above[REGIME_SYMBOL] if REGIME_SYMBOL in above.columns else pd.Series(False, index=days)
    uptrend = above & btc_up.to_numpy()[:, None]
    started = uptrend & ~uptrend.shift(1, fill_value=False)
    events = started & member
    eligible = member & sma.notna()

    avg_volume = vol.rolling(rules.pit.volume_window_days, min_periods=1).mean()
    cost = cost_per_side(avg_volume, SelectionRules()).reindex_like(close)

    last_candle = close.apply(lambda s: s.last_valid_index())
    data_end = days[-1]
    delisted = [
        s for s in close.columns
        if pd.notna(last_candle[s]) and (data_end - last_candle[s]).days > rules.delisted_after_days
    ]
    # Moeda que deixou de negociar sai ao último preço (sem inventar perda total); a ainda ativa fica com a janela
    # incompleta (NaN), que é descartada.
    priced = close.copy()
    if delisted:
        priced[delisted] = close[delisted].ffill()

    forward: dict[int, pd.DataFrame] = {}
    entry = priced.shift(-1)
    entry_cost = cost.shift(-1)
    for h in rules.horizons:
        exit_ = priced.shift(-(1 + h))
        forward[h] = ((1.0 - entry_cost) ** 2 * exit_ / entry - 1.0).replace([np.inf, -np.inf], np.nan)
    return Prepared(events, eligible, forward, priced, sma, cost, last_candle)


def _window(index: pd.Index, period: str, h: int, rules: ValidationRules) -> pd.Series:
    """Dias de sinal que pertencem ao período. Desenvolvimento: entrada e saída até `development_end` (expurgo)."""
    if period == "DESENVOLVIMENTO":
        return pd.Series(index <= rules.dev_end - pd.Timedelta(days=1 + h), index=index)
    return pd.Series(index >= rules.hold_start, index=index)


def independent_positions(positions: np.ndarray, gap: int) -> np.ndarray:
    """Dos dias (posições inteiras, ordenadas) de evento, os independentes: pula quem está a menos de `gap` do último."""
    kept: list[int] = []
    for p in positions.tolist():
        if not kept or p - kept[-1] >= gap:
            kept.append(int(p))
    return np.asarray(kept, dtype=np.int64)


def _series_for(
    prep: Prepared, symbol: str, h: int, period: str, rules: ValidationRules
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(retornos dos eventos com janela completa, retornos dos sinais independentes, retornos de todos os dias
    elegíveis), todos em ordem cronológica."""
    fwd = prep.forward[h][symbol]
    window = _window(fwd.index, period, h, rules).to_numpy()
    ok = fwd.notna().to_numpy() & window
    ev = prep.events[symbol].to_numpy() & ok
    pos = np.flatnonzero(ev)
    keep = independent_positions(pos, h)
    values = fwd.to_numpy(dtype="float64")
    base_mask = prep.eligible[symbol].to_numpy() & ok
    return values[pos], values[keep], values[base_mask]


def count_independent(prep: Prepared, rules: ValidationRules = ValidationRules()) -> pd.DataFrame:
    """Contagem de sinais por moeda, horizonte e período. Só olha QUANTOS sinais há, nunca o valor do retorno
    (apenas se a janela está completa): serve para fixar `N_MIN` antes de qualquer estatística."""
    rows = []
    for symbol in prep.events.columns:
        for h in rules.horizons:
            for period in ("DESENVOLVIMENTO", "TESTE_FINAL"):
                fwd = prep.forward[h][symbol]
                ok = fwd.notna().to_numpy() & _window(fwd.index, period, h, rules).to_numpy()
                pos = np.flatnonzero(prep.events[symbol].to_numpy() & ok)
                rows.append(
                    {"symbol": symbol, "horizon": h, "period": period, "n_events": len(pos),
                     "n_independent": len(independent_positions(pos, h))}
                )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class ExcessStats:
    n_events: int
    n_independent: int
    mean_signal: float
    mean_baseline: float
    excess: float
    ci_low: float
    ci_high: float
    p_value: float
    stable_halves: bool


_NAN = float("nan")


def excess_stats(
    events: np.ndarray, independent: np.ndarray, baseline: np.ndarray, h: int, seed: int, rules: ValidationRules
) -> ExcessStats:
    """Excesso (média dos sinais independentes − média da referência), valor-p pela referência aleatória e IC 95% por
    bootstrap em blocos. Sem sinais ou sem referência, tudo NaN."""
    n, m = len(independent), len(baseline)
    if n == 0 or m == 0:
        return ExcessStats(len(events), n, _NAN, _NAN, _NAN, _NAN, _NAN, _NAN, False)
    mean_s, mean_b = float(independent.mean()), float(baseline.mean())
    excess = mean_s - mean_b
    rng = np.random.default_rng(seed)
    null_means = baseline[rng.integers(0, m, size=(rules.null_draws, n))].mean(axis=1)
    p = (1.0 + float(np.sum(null_means >= mean_s))) / (rules.null_draws + 1.0)
    block_s = max(1, math.ceil(n ** (1.0 / 3.0)))
    boot_s = independent[block_indices(n, block_s, rules.resamples, rng)].mean(axis=1)
    boot_b = baseline[block_indices(m, max(h, 5), rules.resamples, rng)].mean(axis=1)
    lo, hi = np.percentile(boot_s - boot_b, [2.5, 97.5])
    half = n // 2
    stable = bool(n >= 2 and independent[:half].mean() - mean_b > 0 and independent[half:].mean() - mean_b > 0)
    return ExcessStats(len(events), n, mean_s, mean_b, excess, float(lo), float(hi), p, stable)


def _detail_rows(prep: Prepared, period: str, rules: ValidationRules) -> pd.DataFrame:
    rows = []
    for symbol in prep.events.columns:
        for h in rules.horizons:
            ev, ind, base = _series_for(prep, symbol, h, period, rules)
            s = excess_stats(ev, ind, base, h, stable_seed(rules.seed, symbol, h, period), rules)
            rows.append(
                {"symbol": symbol, "horizon": h, "period": period, "n_events": s.n_events,
                 "n_independent": s.n_independent, "mean_signal": s.mean_signal, "mean_baseline": s.mean_baseline,
                 "excess": s.excess, "ci_low": s.ci_low, "ci_high": s.ci_high, "p_value": s.p_value,
                 "p_holm": _NAN, "stable_halves": s.stable_halves, "in_family": False}
            )
    return pd.DataFrame(rows)


def evaluate_development(
    prep: Prepared, rules: ValidationRules = ValidationRules(), n_min: int | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(detalhe, resumo por moeda) do período de desenvolvimento. Holm sobre as combinações (moeda, horizonte) com
    ao menos `n_min` sinais independentes; moeda com menos que isso em algum horizonte fica SEM_EVIDENCIA."""
    minimum = rules.n_min if n_min is None else n_min
    if minimum < 1:
        raise ValueError("N_MIN precisa ser fixado (>= 1) antes de avaliar")
    detail = _detail_rows(prep, "DESENVOLVIMENTO", rules)
    family = detail["n_independent"].ge(minimum) & detail["p_value"].notna()
    detail["in_family"] = family
    adjusted = holm_adjust(detail.loc[family, "p_value"].tolist())
    detail.loc[family, "p_holm"] = adjusted
    return detail.astype(DETAIL_SCHEMA), _summarize(detail, rules, minimum)


def _pick(frame: pd.DataFrame, symbol: str, h: int) -> pd.Series:
    row = frame[frame["symbol"].eq(symbol) & frame["horizon"].eq(h)]
    return row.iloc[0] if not row.empty else pd.Series(dtype="object")


def _summarize(detail: pd.DataFrame, rules: ValidationRules, minimum: int) -> pd.DataFrame:
    rows = []
    for symbol in sorted(detail["symbol"].unique()):
        per = {h: _pick(detail, symbol, h) for h in rules.horizons}
        enough = all(int(r["n_independent"]) >= minimum for r in per.values())
        if not enough:
            status, why = STATUS_NO_EVIDENCE, f"menos de {minimum} sinais independentes em algum horizonte"
        else:
            checks = {
                h: bool(r["p_holm"] < rules.alpha and r["ci_low"] > 0 and r["stable_halves"]) for h, r in per.items()
            }
            if all(checks.values()):
                status, why = STATUS_VALIDATED, "passou nos dois horizontes"
            else:
                failed = [str(h) for h, ok in checks.items() if not ok]
                status, why = STATUS_NOT_VALIDATED, f"não passou em {'/'.join(failed)} dias"
        row: dict[str, object] = {"symbol": symbol, "status": status, "holdout": HOLDOUT_NA, "reason": why}
        for h in (7, 30):
            r = per.get(h)
            row[f"n_independent_{h}"] = int(r["n_independent"]) if r is not None and len(r) else pd.NA
            row[f"excess_{h}"] = float(r["excess"]) if r is not None and len(r) else _NAN
            row[f"ci_low_{h}"] = float(r["ci_low"]) if r is not None and len(r) else _NAN
            row[f"p_holm_{h}"] = float(r["p_holm"]) if r is not None and len(r) else _NAN
            row[f"holdout_n_{h}"] = pd.NA
            row[f"holdout_excess_{h}"] = _NAN
        rows.append(row)
    out = pd.DataFrame(rows)
    for col, dtype in EVIDENCE_SCHEMA.items():
        if col not in out.columns:
            out[col] = pd.Series(dtype=dtype)
    return out[list(EVIDENCE_SCHEMA)].astype(EVIDENCE_SCHEMA)


def apply_holdout(
    summary: pd.DataFrame, prep: Prepared, rules: ValidationRules = ValidationRules()
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Teste final. Só moedas VALIDADA entram; o hold-out só pode revogar (nunca conceder), conforme o documento.

    Revoga se, em algum horizonte, houver pelo menos `holdout_min_signals` sinais independentes e excesso negativo.
    Sem esse mínimo em ambos os horizontes: `INSUFICIENTE` (mantém VALIDADA, não confirmada). Devolve (resumo
    atualizado, detalhe do hold-out).
    """
    detail = _detail_rows(prep, "TESTE_FINAL", rules)
    out = summary.copy()
    for i, row in out.iterrows():
        symbol = str(row["symbol"])
        per = {h: _pick(detail, symbol, h) for h in rules.horizons}
        for h in (7, 30):
            r = per.get(h)
            out.loc[i, f"holdout_n_{h}"] = int(r["n_independent"]) if r is not None and len(r) else 0
            out.loc[i, f"holdout_excess_{h}"] = float(r["excess"]) if r is not None and len(r) else _NAN
        if row["status"] != STATUS_VALIDATED:
            continue
        enough = {h: int(r["n_independent"]) >= rules.holdout_min_signals for h, r in per.items()}
        refuted = [h for h, r in per.items() if enough[h] and float(r["excess"]) < 0]
        if refuted:
            out.loc[i, "status"] = STATUS_REVOKED
            out.loc[i, "holdout"] = HOLDOUT_REFUTED
            out.loc[i, "reason"] = f"excesso negativo no teste final ({'/'.join(map(str, refuted))} dias)"
        elif all(enough.values()):
            out.loc[i, "holdout"] = HOLDOUT_CONFIRMED
        else:
            out.loc[i, "holdout"] = HOLDOUT_INSUFFICIENT
    return out.astype(EVIDENCE_SCHEMA), detail.astype(DETAIL_SCHEMA)


def validated_symbols(evidence: pd.DataFrame) -> tuple[str, ...]:
    """Moedas que podem mostrar COMPRAR."""
    return tuple(str(s) for s in evidence.loc[evidence["status"].eq(STATUS_VALIDATED), "symbol"])


def apply_evidence_to_stage(frame: pd.DataFrame, evidence: pd.DataFrame, buy_stages: Sequence[str]) -> pd.DataFrame:
    """Rebaixa para NEUTRO os estágios de compra (`buy_stages`) de moeda não validada. Sem tabela de evidência, nenhuma
    moeda é validada (falha fechada)."""
    ok = set(validated_symbols(evidence)) if not evidence.empty else set()
    drop = frame["stage"].isin(list(buy_stages)) & ~frame["symbol"].isin(list(ok))
    return frame.assign(stage=frame["stage"].mask(drop, "NEUTRO"))
