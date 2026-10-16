"""Métricas, incerteza e identificação de experimentos da Fase 5 (pesquisa).

Puro (CLAUDE.md §1): sem rede, disco ou relógio; a data da execução é injetada por quem grava o registro.

Incerteza: bootstrap em blocos circulares dos retornos diários PAREADOS (mesmos blocos nas duas séries), que respeita
a dependência serial de curto prazo; valor-p bilateral por bootstrap centrado; correção de Holm para a família de
hipóteses. Anos civis NÃO são observações independentes (mesmo mercado, mesma tendência): nada aqui os trata assim.
A validação estatística da Fase 3 não existe no repositório; estas são as peças mínimas para a Fase 5, não uma
restauração dela.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365
MIN_DAYS = 252
"""Amostra mínima (dias) para Sharpe, Sortino, volatilidade e retorno anualizado; abaixo disso, NaN."""
PRIMARY_BLOCK = 20
BOOTSTRAP_RESAMPLES = 2000
NAN = float("nan")

METRIC_COLUMNS: tuple[str, ...] = (
    "n_days", "total_return_pct", "annual_return_pct", "vol_ann_pct", "sharpe", "sortino", "max_drawdown_pct",
    "recovery_days", "longest_underwater_days", "avg_exposure_pct", "days_invested_pct",
)


def sharpe_of(x: np.ndarray) -> float:
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    return float(np.mean(x)) / sd * math.sqrt(DAYS_PER_YEAR) if sd > 0 else NAN


def drawdown_stats(daily: pd.Series) -> tuple[float, float, float]:
    """(pior queda em %, dias do fundo até recuperar o topo anterior [NaN se nunca recuperou], maior período submerso)."""
    equity = (1.0 + daily).cumprod()
    peak = equity.cummax()
    under = equity < peak
    depth = equity / peak - 1.0
    pos = int(np.argmin(depth.to_numpy(dtype="float64")))
    peak_before = float(peak.iloc[pos])
    after = equity.iloc[pos:]
    recovered = after[after >= peak_before]
    recovery = float((pd.Timestamp(recovered.index[0]) - pd.Timestamp(depth.index[pos])).days) if not recovered.empty else NAN
    longest = run = 0
    for flag in under.tolist():
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return float(depth.min()) * 100.0, recovery, float(longest)


def metrics(daily: pd.Series, exposure: pd.Series | None = None, min_days: int = MIN_DAYS) -> dict[str, float]:
    """Métricas de uma série de retornos diários líquidos (METRIC_COLUMNS). Anualizadas só com `min_days` ou mais."""
    out = dict.fromkeys(METRIC_COLUMNS, NAN)
    n = len(daily)
    out["n_days"] = float(n)
    if n == 0:
        return out
    x = daily.to_numpy(dtype="float64")
    equity = float(np.prod(1.0 + x))
    out["total_return_pct"] = (equity - 1.0) * 100.0
    dd, recovery, longest = drawdown_stats(daily)
    out["max_drawdown_pct"], out["recovery_days"], out["longest_underwater_days"] = dd, recovery, longest
    if n >= min_days:
        out["annual_return_pct"] = (equity ** (DAYS_PER_YEAR / n) - 1.0) * 100.0 if equity > 0 else -100.0
        out["vol_ann_pct"] = float(np.std(x, ddof=1)) * math.sqrt(DAYS_PER_YEAR) * 100.0
        out["sharpe"] = sharpe_of(x)
        downside = math.sqrt(float(np.mean(np.minimum(x, 0.0) ** 2)))
        out["sortino"] = float(np.mean(x)) / downside * math.sqrt(DAYS_PER_YEAR) if downside > 0 else NAN
    if exposure is not None and len(exposure) > 0:
        out["avg_exposure_pct"] = float(exposure.mean()) * 100.0
        out["days_invested_pct"] = float((exposure > 1e-9).mean()) * 100.0
    return out


def effective_sample_size(x: np.ndarray, max_lag: int = 20) -> float:
    """n / (1 + 2·Σ (1 − k/(K+1))·ρ_k): quantas observações independentes a série vale (limitado a [1, n])."""
    n = len(x)
    if n < 3:
        return float(n)
    centered = x - x.mean()
    var = float(np.dot(centered, centered))
    if var <= 0:
        return float(n)
    k_max = min(max_lag, n - 2)
    total = sum((1.0 - k / (k_max + 1)) * float(np.dot(centered[:-k], centered[k:])) / var for k in range(1, k_max + 1))
    return float(min(max(n / max(1.0 + 2.0 * total, 1.0), 1.0), n))


def block_indices(n: int, block: int, resamples: int, rng: np.random.Generator) -> np.ndarray:
    """Índices (resamples × n) de um bootstrap em blocos circulares de tamanho `block`."""
    blocks = math.ceil(n / block)
    starts = rng.integers(0, n, size=(resamples, blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(resamples, blocks * block)[:, :n]


def _sharpe_rows(x: np.ndarray) -> np.ndarray:
    sd = x.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, x.mean(axis=1) / sd * math.sqrt(DAYS_PER_YEAR), np.nan)


@dataclass(frozen=True)
class SharpeComparison:
    n: int
    n_eff: float
    sharpe_a: float
    sharpe_b: float
    diff: float
    ci_low: float
    ci_high: float
    p_value: float
    block: int
    resamples: int
    seed: int

    def row(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.__dict__.items()}


def paired_sharpe_bootstrap(
    a: pd.Series, b: pd.Series, block: int = PRIMARY_BLOCK, resamples: int = BOOTSTRAP_RESAMPLES, seed: int = 0,
    min_days: int = MIN_DAYS,
) -> SharpeComparison:
    """Diferença de Sharpe (a − b) com IC percentil de 95% e valor-p bilateral por bootstrap centrado.

    As séries são alinhadas por data; só os dias comuns entram. Abaixo de `min_days` tudo é NaN (amostra insuficiente).
    """
    joined = pd.concat([a, b], axis=1, join="inner").dropna()
    n = len(joined)
    if n < min_days:
        return SharpeComparison(n, float(n), NAN, NAN, NAN, NAN, NAN, NAN, block, resamples, seed)
    xa, xb = joined.iloc[:, 0].to_numpy(dtype="float64"), joined.iloc[:, 1].to_numpy(dtype="float64")
    idx = block_indices(n, block, resamples, np.random.default_rng(seed))
    diffs = _sharpe_rows(xa[idx]) - _sharpe_rows(xb[idx])
    diffs = diffs[np.isfinite(diffs)]
    point = sharpe_of(xa) - sharpe_of(xb)
    if len(diffs) == 0 or not math.isfinite(point):
        return SharpeComparison(n, effective_sample_size(xa - xb), sharpe_of(xa), sharpe_of(xb), point, NAN, NAN, NAN, block, resamples, seed)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p = (1.0 + float(np.sum(np.abs(diffs - point) >= abs(point)))) / (len(diffs) + 1.0)
    return SharpeComparison(n, effective_sample_size(xa - xb), sharpe_of(xa), sharpe_of(xb), point, float(lo), float(hi), p, block, resamples, seed)


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Valores-p ajustados pelo método de Holm (controla a taxa de erro por família). NaN permanece NaN."""
    valid = [(p, i) for i, p in enumerate(p_values) if math.isfinite(p)]
    m = len(valid)
    out = [NAN] * len(p_values)
    running = 0.0
    for rank, (p, i) in enumerate(sorted(valid)):
        running = max(running, min(1.0, (m - rank) * p))
        out[i] = running
    return out


# ---------------------------------------------------------------------------------------------
# Janelas cronológicas
# ---------------------------------------------------------------------------------------------

def year_windows(index: pd.DatetimeIndex) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Cada ano civil presente em `index`, em ordem cronológica."""
    return {
        str(y): (pd.Timestamp(f"{y}-01-01", tz="UTC"), pd.Timestamp(f"{y}-12-31", tz="UTC"))
        for y in sorted(set(index.year))
    }


def slice_window(series: pd.Series, window: tuple[pd.Timestamp, pd.Timestamp]) -> pd.Series:
    return series[(series.index >= window[0]) & (series.index <= window[1])]


def chronological_split(
    index: pd.DatetimeIndex, train_end: pd.Timestamp, validation_end: pd.Timestamp
) -> dict[str, pd.DatetimeIndex]:
    """TREINO (<= train_end), VALIDACAO (até validation_end) e TESTE (depois), sem sobreposição nem embaralhamento."""
    if not train_end < validation_end:
        raise ValueError("train_end precisa ser anterior a validation_end")
    return {
        "TREINO": index[index <= train_end],
        "VALIDACAO": index[(index > train_end) & (index <= validation_end)],
        "TESTE": index[index > validation_end],
    }


# ---------------------------------------------------------------------------------------------
# Identificação e reprodutibilidade
# ---------------------------------------------------------------------------------------------

def data_fingerprint(candles: pd.DataFrame) -> str:
    """Hash dos candles usados (símbolo, dia e fechamento), independente da ordem das linhas."""
    h = hashlib.sha256()
    frame = candles.sort_values(["symbol", "timestamp"])
    for symbol, g in frame.groupby("symbol", sort=True):
        h.update(str(symbol).encode())
        h.update(g["timestamp"].dt.tz_convert(None).to_numpy(dtype="datetime64[ns]").astype("int64").tobytes())
        h.update(g["close"].to_numpy(dtype="float64").tobytes())
    return h.hexdigest()[:32]


def experiment_id(config: Mapping[str, object], data_fp: str) -> str:
    """ID determinístico: mesma configuração e mesmos dados -> mesmo ID (a data da execução não entra)."""
    payload = json.dumps({"config": config, "data": data_fp}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def results_digest(results: pd.DataFrame, decimals: int = 8) -> str:
    """Hash dos resultados com os números arredondados (tolerância numérica documentada: 1e-8)."""
    text = results.round(decimals).to_csv(index=False, float_format=f"%.{decimals}f")
    return hashlib.sha256(text.encode()).hexdigest()[:32]
