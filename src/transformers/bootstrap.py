"""Incerteza de métricas de séries temporais: bootstrap estacionário em blocos, intervalos e testes pareados.

Puro (CLAUDE.md §1): a aleatoriedade vem só de `numpy.random.default_rng(seed)` com a semente recebida, então o
mesmo dado e a mesma semente dão sempre o mesmo resultado.

Por que blocos. Retornos diários de cripto têm pouca autocorrelação na média, mas muita na volatilidade
(agrupamento) e, nas estratégias de tendência, longos trechos em caixa ou investidos. O bootstrap IID trocaria a
ordem dos dias e destruiria essa estrutura, subestimando a incerteza de Sharpe e retorno. Usa-se o bootstrap
ESTACIONÁRIO (Politis e Romano, 1994): blocos de comprimento geométrico com média L, contínuos e circulares.

Comprimento médio do bloco. Automático, pelo método de Politis e White (2004), com a correção de Patton, Politis e
White (2009), calculado sobre cada série envolvida (a estratégia, a referência, a diferença entre elas e os
retornos absolutos, que carregam o agrupamento de volatilidade); usa-se o MAIOR (mais conservador), limitado a
[`min_block`, n / 3]. A sensibilidade a L fixo é publicada pela validação (ex.: 5, 20 e 60 dias).

Comparação pareada. Estratégia e referência são reamostradas com os MESMOS índices (os mesmos dias), o que preserva
a correlação entre elas. Estatística principal: diferença de Sharpe anualizado.

Intervalo: percentil (nível `ci_level`, padrão 90% bilateral, coerente com o teste unilateral a 5%). p-valor
unilateral de H0: θ <= 0 contra H1: θ > 0, pela distribuição centrada (θ* − θ̂ aproxima a de θ̂ − θ):
    p = (1 + #{θ*_b − θ̂ >= θ̂}) / (B + 1).
Ajuste para várias estratégias com os mesmos índices (`max_stat_pvalues`): máximo da estatística centrada
(passo único, no espírito do Reality Check de White, 2000), que respeita a correlação entre as estratégias.

Limites: o intervalo percentil não corrige viés nem assimetria (não é BCa nem studentizado); com poucos anos de
dados e poucos ciclos de mercado, os blocos não recriam regimes que a amostra não contém. Um intervalo é sobre a
estimativa nesta amostra, não uma garantia de retorno futuro.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .metrics import PERIODS_PER_YEAR, cagr_rows, sharpe_rows

Floats = NDArray[np.float64]
Ints = NDArray[np.int64]
Statistic = Callable[[Floats], Floats]  # matriz (reamostras x dias) -> um valor por reamostra


@dataclass(frozen=True)
class BootstrapConfig:
    n_boot: int = 2000
    seed: int = 20261016
    ci_level: float = 0.90
    block: float | None = None   # None = automático (Politis e White); um número fixa o comprimento médio
    min_block: float = 1.0

    def __post_init__(self) -> None:
        if self.n_boot < 100:
            raise ValueError("n_boot >= 100")
        if not 0.5 <= self.ci_level < 1:
            raise ValueError("ci_level em [0,5; 1)")
        if self.block is not None and self.block < 1:
            raise ValueError("bloco >= 1")


# ---------------------------------------------------------------------------------------------
# Comprimento do bloco
# ---------------------------------------------------------------------------------------------

def optimal_block_length(x: Floats) -> float:
    """Comprimento médio ótimo do bloco do bootstrap estacionário (Politis e White, 2004; Patton et al., 2009).

    1. m̂ = menor defasagem a partir da qual K_N autocorrelações seguidas são insignificantes
       (|ρ| < 2·√(log10(n)/n)), K_N = max(5, ⌈√log10(n)⌉); M = min(2·m̂, m_max), m_max = ⌈√n⌉ + K_N.
    2. Janela plana-trapezoidal λ(t) = 1 se |t| <= 1/2, 2(1 − |t|) se 1/2 < |t| <= 1.
       G = Σ λ(k/M)·|k|·γ(k), g(0) = Σ λ(k/M)·γ(k), D = 2·g(0)².
    3. L = (2G²/D)^(1/3) · n^(1/3), limitado a [1, min(3√n, n/3)].
    """
    v = np.asarray(x, dtype="float64")
    n = v.size
    if n < 10:
        return 1.0
    e = v - v.mean()
    var = float(e @ e) / n
    if var <= 0:
        return 1.0
    kn = max(5, math.ceil(math.sqrt(math.log10(n))))
    m_max = math.ceil(math.sqrt(n)) + kn
    m_max = min(m_max, n - 1)
    acv = np.array([float(e[k:] @ e[: n - k]) / n for k in range(m_max + 1)])
    rho = np.abs(acv / acv[0])
    cv = 2.0 * math.sqrt(math.log10(n) / n)
    m_hat: int | None = None
    for m in range(1, m_max - kn + 1):
        if np.all(rho[m + 1 : m + 1 + kn] < cv):
            m_hat = m
            break
    big_m = min(2 * m_hat, m_max) if m_hat is not None else m_max
    k = np.arange(1, big_m + 1)
    t = k / big_m
    lam = np.where(t <= 0.5, 1.0, 2.0 * (1.0 - t))
    g = float(2.0 * np.sum(lam * k * acv[1 : big_m + 1]))
    g0 = float(acv[0] + 2.0 * np.sum(lam * acv[1 : big_m + 1]))
    d = 2.0 * g0 * g0
    if d <= 0:
        return 1.0
    length = (2.0 * g * g / d) ** (1.0 / 3.0) * n ** (1.0 / 3.0)
    upper = min(3.0 * math.sqrt(n), n / 3.0)
    return float(min(max(length, 1.0), upper))


def block_length(series: Sequence[Floats], cfg: BootstrapConfig) -> float:
    """Comprimento médio usado: o fixo de `cfg`, ou o maior automático entre as séries, seus valores absolutos e
    (se houver duas) a diferença entre elas, limitado a [cfg.min_block, n/3]."""
    n = int(series[0].size)
    if cfg.block is not None:
        return float(min(cfg.block, max(1.0, n / 3.0)))
    candidates = [optimal_block_length(s) for s in series]
    candidates += [optimal_block_length(np.abs(s - s.mean())) for s in series]
    if len(series) == 2:
        candidates.append(optimal_block_length(series[0] - series[1]))
    return float(min(max(max(candidates), cfg.min_block), max(1.0, n / 3.0)))


# ---------------------------------------------------------------------------------------------
# Reamostragem
# ---------------------------------------------------------------------------------------------

def stationary_indices(n: int, n_boot: int, mean_block: float, rng: np.random.Generator) -> Ints:
    """Índices (n_boot x n) do bootstrap estacionário: cada posição começa um bloco novo com probabilidade 1/L
    (em um dia sorteado) ou continua o bloco anterior no dia seguinte, circularmente."""
    if n <= 0:
        return np.zeros((n_boot, 0), dtype=np.int64)
    p = 1.0 / max(mean_block, 1.0)
    starts = rng.integers(0, n, size=(n_boot, n), dtype=np.int64)
    new = rng.random((n_boot, n)) < p
    new[:, 0] = True
    t = np.arange(n, dtype=np.int64)
    last = np.maximum.accumulate(np.where(new, t, 0), axis=1)
    return np.asarray((np.take_along_axis(starts, last, axis=1) + (t - last)) % n, dtype=np.int64)


@dataclass(frozen=True)
class Resampler:
    """Índices compartilhados por todas as estatísticas de uma mesma família (mesmos dias reamostrados)."""

    indices: Ints
    block: float
    cfg: BootstrapConfig

    @property
    def n_obs(self) -> int:
        return int(self.indices.shape[1])


def make_resampler(series: Sequence[Floats], cfg: BootstrapConfig) -> Resampler:
    """Índices para séries alinhadas de mesmo tamanho (mesmo calendário)."""
    sizes = {int(s.size) for s in series}
    if len(sizes) != 1:
        raise ValueError("as séries precisam estar alinhadas no mesmo calendário")
    for s in series:
        if not np.isfinite(s).all():
            raise ValueError("série com valor ausente: alinhe e trate as lacunas antes do bootstrap")
    length = block_length(series, cfg)
    rng = np.random.default_rng(cfg.seed)
    return Resampler(stationary_indices(sizes.pop(), cfg.n_boot, length, rng), length, cfg)


# ---------------------------------------------------------------------------------------------
# Estatísticas, intervalos e p-valores
# ---------------------------------------------------------------------------------------------

def sharpe_stat(periods_per_year: int = PERIODS_PER_YEAR) -> Statistic:
    return lambda x: sharpe_rows(x, periods_per_year)


def cagr_stat(periods_per_year: int = PERIODS_PER_YEAR) -> Statistic:
    return lambda x: cagr_rows(x, periods_per_year)


@dataclass(frozen=True)
class Estimate:
    estimate: float
    ci_low: float
    ci_high: float
    p_value: float     # unilateral, H0: θ <= 0 (só faz sentido para diferenças e excessos)
    block: float
    n_obs: int
    n_boot: int
    draws: Floats      # θ* de cada reamostra (para ajustes de família)


def _summarize(estimate: float, draws: Floats, res: Resampler) -> Estimate:
    finite = draws[np.isfinite(draws)]
    if not math.isfinite(estimate) or finite.size < 0.9 * draws.size:
        nan = math.nan
        return Estimate(nan, nan, nan, nan, res.block, res.n_obs, int(draws.size), draws)
    alpha = 1.0 - res.cfg.ci_level
    low, high = np.quantile(finite, [alpha / 2.0, 1.0 - alpha / 2.0])
    exceed = int(np.sum(finite - estimate >= estimate))
    p = (1.0 + exceed) / (finite.size + 1.0)
    return Estimate(float(estimate), float(low), float(high), float(p), res.block, res.n_obs, int(draws.size), draws)


def bootstrap_statistic(x: Floats, stat: Statistic, res: Resampler) -> Estimate:
    """Estimativa, intervalo e p-valor (H0: θ <= 0) de `stat` sobre uma série."""
    estimate = float(stat(x[None, :])[0])
    return _summarize(estimate, stat(x[res.indices]), res)


def bootstrap_difference(x: Floats, y: Floats, stat: Statistic, res: Resampler) -> Estimate:
    """θ = stat(x) − stat(y), com x e y reamostrados nos mesmos dias (pareado)."""
    estimate = float(stat(x[None, :])[0] - stat(y[None, :])[0])
    return _summarize(estimate, stat(x[res.indices]) - stat(y[res.indices]), res)


def max_stat_pvalues(estimates: Sequence[Estimate]) -> list[float]:
    """p-valores ajustados de passo único pelo máximo da estatística centrada entre as hipóteses (mesmos índices):
    p_k = (1 + #{b: max_j (θ*_jb − θ̂_j) >= θ̂_k}) / (B + 1). Hipótese sem estimativa = NaN (não entra no máximo).
    O p da melhor estratégia é o do "Reality Check" para a pergunta "a melhor supera a sua referência?"."""
    valid = [e for e in estimates if math.isfinite(e.estimate)]
    if not valid:
        return [math.nan for _ in estimates]
    sizes = {e.draws.size for e in valid}
    if len(sizes) != 1:
        raise ValueError("as estimativas precisam vir das mesmas reamostras")
    centered = np.vstack([e.draws - e.estimate for e in valid])
    centered = np.where(np.isfinite(centered), centered, -np.inf)
    worst = centered.max(axis=0)
    b = worst.size
    return [float((1.0 + np.sum(worst >= e.estimate)) / (b + 1.0)) if math.isfinite(e.estimate) else math.nan
            for e in estimates]
