"""Estudo de risco: a regra SMA 200 reduz queda máxima e volatilidade contra comprar e segurar? Protocolo: docs/sma200_risk.md.

Puro (CLAUDE.md §1). Por moeda, compara a curva da regra (posicionada no dia d se a moeda e o BTC estavam acima da SMA 200
no fechamento de d-2, em caixa senão, pagando custo a cada mudança de posição) com a de comprar e segurar nos mesmos dias.
O intervalo vem de um bootstrap em blocos de calendário (mesmos dias para todas as moedas).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config
from .signal_validation import Prepared, ValidationRules, stable_seed
from .stats import holm_adjust

MIN_DAYS = 365
BLOCK_DAYS = 60
ANNUAL = 365.0
PERIOD_DEV = "DESENVOLVIMENTO"
PERIOD_TEST = "TESTE_FINAL"
STATUS_REDUCES = "REDUZ"
STATUS_NOT_SHOWN = "NAO_DEMONSTRADO"
STATUS_NOT_CONFIRMED = "NAO_CONFIRMADO"
_NAN = float("nan")


@dataclass(frozen=True)
class CoinPath:
    """Retornos diários (0 fora dos dias do conjunto) da regra e de comprar e segurar, e a máscara dos dias do conjunto."""

    symbol: str
    strategy: np.ndarray
    hold: np.ndarray
    mask: np.ndarray
    exposure: float


def _position(prep: Prepared) -> pd.DataFrame:
    if prep.priced is None or prep.sma is None:
        raise ValueError("Prepared sem preços/SMA")
    above = prep.priced.gt(prep.sma) & prep.sma.notna()
    btc_up = above[config.REGIME_SYMBOL] if config.REGIME_SYMBOL in above.columns else pd.Series(False, index=above.index)
    up = above & btc_up.to_numpy()[:, None]
    return up.shift(2, fill_value=False).astype(bool)


def net_returns(position: np.ndarray, r: np.ndarray, cost: np.ndarray) -> np.ndarray:
    """Retorno diário líquido: posição × retorno − custo por lado × |mudança de posição|; a posição que fica aberta no
    fim da série paga a saída no último dia."""
    change = np.abs(np.diff(position, prepend=0.0))
    paid = change * cost
    if position[-1] > 0:
        paid[-1] += cost[-1]
    out: np.ndarray = position * r - paid
    return out


def coin_paths(prep: Prepared, period: str, rules: ValidationRules = ValidationRules()) -> list[CoinPath]:
    """Uma `CoinPath` por moeda com pelo menos `MIN_DAYS` dias do conjunto no período."""
    if prep.priced is None or prep.cost is None:
        raise ValueError("Prepared sem preços/custos")
    index = prep.priced.index
    in_period = (index <= rules.dev_end) if period == PERIOD_DEV else (index >= rules.hold_start)
    ret = prep.priced.pct_change(fill_method=None)
    pos_all = _position(prep)
    out: list[CoinPath] = []
    for symbol in prep.priced.columns:
        mask = prep.eligible[symbol].to_numpy() & in_period & ret[symbol].notna().to_numpy()
        if int(mask.sum()) < MIN_DAYS:
            continue
        r = np.where(mask, ret[symbol].to_numpy(dtype="float64"), 0.0)
        cost = np.nan_to_num(prep.cost[symbol].to_numpy(dtype="float64"), nan=0.0)
        pos = (pos_all[symbol].to_numpy() & mask).astype("float64")
        hold = mask.astype("float64")
        out.append(CoinPath(
            str(symbol), net_returns(pos, r, cost), net_returns(hold, r, cost), mask, float(pos[mask].mean()),
        ))
    return out


def drawdown(returns: np.ndarray) -> np.ndarray:
    """Queda máxima (positiva) de cada linha de retornos diários; aceita 1-D ou 2-D (reamostragens × dias)."""
    equity = np.cumprod(1.0 + returns, axis=-1)
    peak = np.maximum.accumulate(np.maximum(equity, 1.0), axis=-1)
    out: np.ndarray = np.max(1.0 - equity / peak, axis=-1)
    return out


def volatility(returns: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Desvio padrão anualizado dos retornos nos dias da máscara (1-D ou 2-D)."""
    n = np.maximum(mask.sum(axis=-1), 2)
    mean = (returns * mask).sum(axis=-1) / n
    var = (((returns - mean[..., None]) ** 2) * mask).sum(axis=-1) / (n - 1)
    out: np.ndarray = np.sqrt(var) * math.sqrt(ANNUAL)
    return out


def coin_table(paths: list[CoinPath]) -> pd.DataFrame:
    rows = []
    for p in paths:
        ctrl = p.exposure * p.hold
        mask = p.mask.astype("float64")
        rows.append({
            "symbol": p.symbol, "days": int(p.mask.sum()), "exposure": p.exposure,
            "mdd_strategy": float(drawdown(p.strategy)), "mdd_hold": float(drawdown(p.hold)),
            "mdd_control": float(drawdown(ctrl)),
            "vol_strategy": float(volatility(p.strategy, mask)), "vol_hold": float(volatility(p.hold, mask)),
            "vol_control": float(volatility(ctrl, mask)),
            "total_return_strategy": float(np.prod(1.0 + p.strategy) - 1.0),
            "total_return_hold": float(np.prod(1.0 + p.hold) - 1.0),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["mdd_reduction"] = frame["mdd_hold"] - frame["mdd_strategy"]
    frame["vol_reduction"] = frame["vol_hold"] - frame["vol_strategy"]
    return frame.astype({"symbol": "string"})


def _paired_reductions(paths: list[CoinPath], idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Média entre moedas da redução (queda máxima, volatilidade) em cada caminho reamostrado `idx` (reamostragens × dias)."""
    mdd = np.empty((len(paths), idx.shape[0]))
    vol = np.empty_like(mdd)
    for k, p in enumerate(paths):
        s, h, m = p.strategy[idx], p.hold[idx], p.mask[idx].astype("float64")
        mdd[k] = drawdown(h) - drawdown(s)
        vol[k] = volatility(h, m) - volatility(s, m)
    return np.mean(mdd, axis=0), np.mean(vol, axis=0)


def _block_indices_days(n_days: int, resamples: int, rng: np.random.Generator) -> np.ndarray:
    blocks = math.ceil(n_days / BLOCK_DAYS)
    starts = rng.integers(0, n_days, size=(resamples, blocks))
    idx = (starts[:, :, None] + np.arange(BLOCK_DAYS)[None, None, :]) % n_days
    out: np.ndarray = idx.reshape(resamples, blocks * BLOCK_DAYS)[:, :n_days]
    return out


def evaluate_risk(
    prep: Prepared, rules: ValidationRules = ValidationRules(), resamples: int | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(resumo por métrica com IC, Holm e veredito; tabela por moeda) no desenvolvimento."""
    paths = coin_paths(prep, PERIOD_DEV, rules)
    table = coin_table(paths)
    if not paths:
        raise ValueError("nenhuma moeda com dias suficientes")
    count = rules.resamples if resamples is None else resamples
    rng = np.random.default_rng(stable_seed(rules.seed, "RISK"))
    boot_mdd, boot_vol = _paired_reductions(paths, _block_indices_days(len(paths[0].strategy), count, rng))
    rows = []
    for metric, col, level, boot in (
        ("max_drawdown", "mdd_reduction", "mdd", boot_mdd), ("volatility", "vol_reduction", "vol", boot_vol)
    ):
        observed = float(table[col].mean())
        lo, hi = np.percentile(boot, [2.5, 97.5])
        p = (1.0 + float(np.sum(boot - observed >= observed))) / (count + 1.0)
        rows.append({
            "metric": metric, "n_coins": len(table), "reduction": observed, "ci_low": float(lo), "ci_high": float(hi),
            "p_value": p, "median_reduction": float(table[col].median()),
            "share_coins_reduced": float((table[col] > 0).mean()),
            "mean_hold": float(table[f"{level}_hold"].mean()), "mean_strategy": float(table[f"{level}_strategy"].mean()),
            "mean_control": float(table[f"{level}_control"].mean()), "mean_exposure": float(table["exposure"].mean()),
            "mean_return_hold": float(table["total_return_hold"].mean()),
            "mean_return_strategy": float(table["total_return_strategy"].mean()),
            "median_return_hold": float(table["total_return_hold"].median()),
            "median_return_strategy": float(table["total_return_strategy"].median()),
        })
    summary = pd.DataFrame(rows)
    summary["p_holm"] = holm_adjust(summary["p_value"].tolist())
    passed = summary["p_holm"].lt(rules.alpha) & summary["ci_low"].gt(0)
    summary["status"] = STATUS_REDUCES if bool(passed.all()) else STATUS_NOT_SHOWN
    return summary, table


def confirm_on_test(summary: pd.DataFrame, prep: Prepared, rules: ValidationRules = ValidationRules()) -> pd.DataFrame:
    """Teste final: só calculado se o desenvolvimento mostrou redução; só contradiz (redução média negativa)."""
    out = summary.assign(test_n_coins=pd.array([pd.NA] * len(summary), dtype="Int64"), test_reduction=_NAN)
    if not bool(summary["status"].eq(STATUS_REDUCES).all()):
        return out
    table = coin_table(coin_paths(prep, PERIOD_TEST, rules))
    if table.empty:
        return out
    out["test_n_coins"] = len(table)
    out["test_reduction"] = [float(table["mdd_reduction"].mean()), float(table["vol_reduction"].mean())]
    if bool(out["test_reduction"].lt(0).any()):
        out["status"] = STATUS_NOT_CONFIRMED
    return out
