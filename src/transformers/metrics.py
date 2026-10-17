"""Métricas de desempenho a partir de uma série diária de retornos do patrimônio, com convenções explícitas.

Puro (CLAUDE.md §1). É a base da validação estatística (Fase 3): toda métrica sai da MESMA série temporal (retorno
diário do patrimônio produzido pelo motor único, já líquido de taxa, spread e slippage), nunca de retornos por
operação misturados com retornos diários.

Convenções (`MetricConventions`):
    unidade             retorno simples diário do patrimônio, fechamento a fechamento (365 dias por ano: cripto
                        negocia todos os dias). Dias em caixa entram com retorno 0 (o caixa não rende): a métrica é
                        da carteira inteira, não só dos dias comprados.
    taxa livre de risco 0. É coerente com o motor (caixa em USDT sem rendimento): Sharpe e Sortino medem o
                        excesso sobre ficar em caixa no próprio motor, não sobre um título.
    retorno anualizado  geométrico: patrimônio final ^ (365 / n) − 1. Só com n >= `min_obs_annual` (365): anualizar
                        poucos meses multiplica o ruído e é omitido (NaN), não estimado.
    volatilidade        desvio padrão amostral (ddof = 1) dos retornos diários × √365.
    Sharpe              média diária / desvio diário × √365. Só com n >= `min_obs_ratio` (180). Série toda em caixa
                        (todos os retornos exatamente 0) tem Sharpe 0: o excesso sobre o caixa é nulo; desvio 0 com
                        média diferente de 0 fica NaN.
    Sortino             média diária / desvio de baixa × √365, desvio de baixa = √(média de min(r, 0)²) sobre TODOS
                        os dias (alvo 0). Mesmo mínimo do Sharpe.
    pior queda          mínimo de patrimônio / máximo anterior − 1 (sobre o patrimônio no fechamento, partindo de 1
                        no dia anterior ao primeiro retorno).
    duração da queda    maior sequência de dias abaixo do máximo anterior (dias de calendário); `drawdown_open`
                        indica que a maior queda ainda não tinha sido recuperada no fim da amostra.
    Calmar              retorno anualizado / |pior queda|. Mesmo mínimo do anualizado.
    exposição           média de (valor em ativos / patrimônio) no fechamento; tempo investido = fração dos dias
                        com exposição > 0.

Estas métricas DESCREVEM a amostra. Incerteza (intervalos, testes) está em `bootstrap.py`; um Sharpe pontual, mesmo
com n acima do mínimo, não é evidência de nada sozinho.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .backtest_engine import BacktestResult, summarize, total_costs

Floats = NDArray[np.float64]

PERIODS_PER_YEAR = 365


@dataclass(frozen=True)
class MetricConventions:
    periods_per_year: int = PERIODS_PER_YEAR
    min_obs_ratio: int = 180    # abaixo: Sharpe, Sortino e volatilidade = NaN (estimativa instável demais)
    min_obs_annual: int = 365   # abaixo: retorno anualizado e Calmar = NaN (anualizar menos de 1 ano)
    exposure_eps: float = 1e-6  # exposição acima disso conta como dia investido

    def __post_init__(self) -> None:
        if self.periods_per_year <= 0 or self.min_obs_ratio < 2 or self.min_obs_annual < 1:
            raise ValueError("convenções de métrica inválidas")


METRICS_SCHEMA: dict[str, str] = {
    "n_obs": "Int64",
    "start": "datetime64[ns, UTC]",
    "end": "datetime64[ns, UTC]",
    "total_return_pct": "float64",
    "cagr_pct": "float64",
    "vol_pct": "float64",
    "sharpe": "float64",
    "sortino": "float64",
    "max_drawdown_pct": "float64",
    "max_drawdown_days": "Int64",
    "drawdown_open": "boolean",
    "calmar": "float64",
    "exposure_pct": "float64",
    "time_in_market_pct": "float64",
}

ENGINE_METRICS_SCHEMA: dict[str, str] = {
    **METRICS_SCHEMA,
    "turnover_per_year": "float64",  # notional negociado / patrimônio médio, por ano
    "cost_pct": "float64",           # taxa + spread + slippage pagos, % do capital inicial
    "n_entries": "Int64",            # entradas em ativos (de zerado para comprado)
}


def sharpe_rows(x: Floats, periods_per_year: int = PERIODS_PER_YEAR) -> Floats:
    """Sharpe anualizado de cada linha de `x` (matriz reamostras × dias). Desvio zero = NaN."""
    mean = x.mean(axis=1)
    sd = x.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(sd > 0, mean / sd * math.sqrt(periods_per_year), np.where(np.all(x == 0, axis=1), 0.0, np.nan))
    return np.asarray(out, dtype="float64")


def cagr_rows(x: Floats, periods_per_year: int = PERIODS_PER_YEAR) -> Floats:
    """Retorno anualizado geométrico de cada linha (fração). Patrimônio <= 0 = −100%."""
    growth = np.prod(1.0 + x, axis=1)
    n = x.shape[1]
    with np.errstate(invalid="ignore"):
        out = np.where(growth > 0, np.power(np.maximum(growth, 1e-300), periods_per_year / n) - 1.0, -1.0)
    return np.asarray(out, dtype="float64")


def drawdown_stats(returns: pd.Series) -> tuple[float, int, bool]:
    """(pior queda em fração, maior duração abaixo do topo em dias, a maior queda segue aberta no fim)."""
    r = returns.to_numpy(dtype="float64")
    if r.size == 0:
        return math.nan, 0, False
    equity = np.concatenate([[1.0], np.cumprod(1.0 + r)])
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    under = dd < -1e-12
    longest = run = 0
    for flag in under[1:]:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    trough = int(np.argmin(dd))
    still_open = bool(np.all(under[trough:])) and float(dd.min()) < 0
    return float(dd.min()), longest, still_open


def return_metrics(
    returns: pd.Series,
    exposure: pd.Series | None = None,
    conventions: MetricConventions = MetricConventions(),
) -> dict[str, object]:
    """Métricas (METRICS_SCHEMA) de uma série diária de retornos simples. NaN no lugar de estimativas que a
    amostra não sustenta (ver convenções); retornos ausentes não são aceitos (o motor nunca os produz)."""
    r = returns.astype("float64")
    nan = math.nan
    n = len(r)
    if n == 0:
        return {"n_obs": 0, "start": pd.NaT, "end": pd.NaT, **{k: nan for k in (
            "total_return_pct", "cagr_pct", "vol_pct", "sharpe", "sortino", "max_drawdown_pct", "calmar",
            "exposure_pct", "time_in_market_pct")}, "max_drawdown_days": 0, "drawdown_open": False}
    if not np.isfinite(r.to_numpy()).all():
        raise ValueError("série de retornos com valor ausente ou infinito: trate a lacuna antes (não vira zero)")
    ppy = conventions.periods_per_year
    x = np.asarray(r.to_numpy(dtype="float64"), dtype=np.float64)[None, :]
    growth = float(np.prod(1.0 + r.to_numpy()))
    dd, dd_days, dd_open = drawdown_stats(r)
    enough_ratio = n >= conventions.min_obs_ratio
    enough_annual = n >= conventions.min_obs_annual
    sd = float(r.std(ddof=1)) if n > 1 else nan
    downside = math.sqrt(float(np.mean(np.minimum(r.to_numpy(), 0.0) ** 2)))
    cagr = float(cagr_rows(x, ppy)[0]) if enough_annual else nan
    exp = exposure.reindex(r.index).astype("float64") if exposure is not None else None
    return {
        "n_obs": n,
        "start": pd.Timestamp(r.index[0]),
        "end": pd.Timestamp(r.index[-1]),
        "total_return_pct": (growth - 1.0) * 100.0,
        "cagr_pct": cagr * 100.0,
        "vol_pct": sd * math.sqrt(ppy) * 100.0 if enough_ratio else nan,
        "sharpe": float(sharpe_rows(x, ppy)[0]) if enough_ratio else nan,
        "sortino": (float(r.mean()) / downside * math.sqrt(ppy) if downside > 0
                    else 0.0 if bool((r == 0).all()) else nan) if enough_ratio else nan,
        "max_drawdown_pct": dd * 100.0,
        "max_drawdown_days": dd_days,
        "drawdown_open": dd_open,
        "calmar": cagr / abs(dd) if enough_annual and dd < 0 else nan,
        "exposure_pct": float(exp.mean()) * 100.0 if exp is not None else nan,
        "time_in_market_pct": float(exp.gt(conventions.exposure_eps).mean()) * 100.0 if exp is not None else nan,
    }


def engine_metrics(result: BacktestResult, conventions: MetricConventions = MetricConventions()) -> dict[str, object]:
    """`return_metrics` do patrimônio do motor + giro, custos e entradas (ENGINE_METRICS_SCHEMA)."""
    base = return_metrics(result.returns, result.exposure, conventions)
    if result.returns.empty:
        return {**base, "turnover_per_year": math.nan, "cost_pct": math.nan, "n_entries": 0}
    s = summarize(result)
    return {
        **base,
        "turnover_per_year": _number(s["turnover_per_year"]),
        "cost_pct": total_costs(result)["total"] * 100.0,
        "n_entries": int(_number(s["n_trades"])),
    }


def _number(value: float | pd.Timestamp) -> float:
    if isinstance(value, pd.Timestamp):
        raise TypeError("métrica numérica esperada")
    return float(value)


def metrics_frame(rows: list[dict[str, object]], schema: dict[str, str]) -> pd.DataFrame:
    """Linhas de métricas -> DataFrame tipado (colunas extras são mantidas antes das do schema)."""
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
    out = pd.DataFrame(rows)
    for col, dtype in schema.items():
        if col in out.columns and dtype.startswith("datetime64"):
            out[col] = pd.to_datetime(out[col], utc=True)
    return out.astype({c: t for c, t in schema.items() if c in out.columns})
