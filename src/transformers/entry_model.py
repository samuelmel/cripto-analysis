"""Modelo em modo sombra (F): regressão logística L2 em NumPy, walk-forward anual. Protocolo: docs/entry_signals.md.

Puro (CLAUDE.md §1) e determinístico: Newton/IRLS sem aleatoriedade, mesma entrada dá o mesmo resultado.

Alvo: a moeda supera o BTC em 30 dias (retorno líquido, abertura de `t+1` à abertura de `t+31`, o BTC calculado da mesma
forma). Features: só dados até `t`. Para cada ano `Y`, a dobra treina com as linhas de dias até 31/12 de `Y−1` menos o
expurgo de 31 dias (todo alvo de treino termina antes do corte) e prevê os dias de `Y`. Padronização (média e desvio) e
penalidade L2 vêm só das linhas de treino da dobra; nada é recalculado com a dobra de teste.

Penalidade: log-verossimilhança somada + (λ/2)·‖w‖², intercepto sem penalidade (equivale ao C = 1/λ do scikit-learn).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .entry_signals import Panel, forward_returns, trailing_return

FEATURES: tuple[str, ...] = (
    "ret_30", "ret_90", "vol_30", "vol_90", "volume_ratio_7_90",
    "dist_sma_50", "dist_sma_100", "dist_sma_200", "drawdown_90", "fng", "fng_change_7",
)
TARGET_HORIZON = 30
PURGE_DAYS = 31
L2_LAMBDA = 1.0
MAX_ITER = 100
TOL = 1e-10

FOLD_SCHEMA: dict[str, str] = {
    "year": "int64",
    "train_end": "datetime64[ns, UTC]",   # último dia de sinal admitido no treino (corte − expurgo)
    "last_target_end": "datetime64[ns, UTC]",
    "n_train": "int64",
    "n_test": "int64",
    "positive_rate": "float64",
    "iterations": "int64",
}


def _rolling(frame: pd.DataFrame, window: int, fn: str) -> pd.DataFrame:
    """Janela sobre os candles de cada moeda (dias sem candle não contam), alinhada ao calendário."""
    out = {}
    for symbol in frame.columns:
        col = frame[symbol].dropna()
        roll = col.rolling(window, min_periods=window)
        res = roll.mean() if fn == "mean" else roll.max() if fn == "max" else roll.std()
        out[symbol] = res.reindex(frame.index)
    return pd.DataFrame(out, index=frame.index, columns=frame.columns)


def model_features(panel: Panel, fng: pd.Series | None) -> dict[str, pd.DataFrame]:
    """Features largas (dia × moeda), todas calculadas só com dados até `t`. `fng`: índice Fear & Greed por dia (UTC)."""
    close = panel.close
    logret = pd.DataFrame(
        {s: np.log(close[s].dropna()).diff().reindex(close.index) for s in close.columns},
        index=close.index, columns=close.columns,
    )
    feats: dict[str, pd.DataFrame] = {
        "ret_30": trailing_return(close, 30),
        "ret_90": trailing_return(close, 90),
        "vol_30": _rolling(logret, 30, "std"),
        "vol_90": _rolling(logret, 90, "std"),
        "volume_ratio_7_90": _rolling(panel.quote_volume, 7, "mean") / _rolling(panel.quote_volume, 90, "mean"),
        "dist_sma_50": close / _rolling(close, 50, "mean") - 1.0,
        "dist_sma_100": close / _rolling(close, 100, "mean") - 1.0,
        "dist_sma_200": close / _rolling(close, 200, "mean") - 1.0,
        "drawdown_90": close / _rolling(close, 90, "max") - 1.0,
    }
    level = (fng.reindex(close.index).astype("float64") if fng is not None
             else pd.Series(np.nan, index=close.index, dtype="float64"))
    change = level - level.shift(7)
    feats["fng"] = pd.DataFrame(np.repeat(level.to_numpy()[:, None], close.shape[1], axis=1),
                                index=close.index, columns=close.columns)
    feats["fng_change_7"] = pd.DataFrame(np.repeat(change.to_numpy()[:, None], close.shape[1], axis=1),
                                         index=close.index, columns=close.columns)
    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in feats.items()}


def outperform_target(panel: Panel, btc: str) -> pd.DataFrame:
    """1.0 se o retorno líquido de 30 dias (aberturas) da moeda supera o do BTC no mesmo intervalo; NaN sem janela."""
    fwd = forward_returns(panel, TARGET_HORIZON)
    if btc not in fwd.columns:
        return pd.DataFrame(np.nan, index=fwd.index, columns=fwd.columns)
    out = fwd.gt(fwd[btc], axis=0).astype("float64")
    return out.where(fwd.notna() & fwd[btc].notna().to_numpy()[:, None])


def stack_rows(features: dict[str, pd.DataFrame], target: pd.DataFrame, member: pd.DataFrame) -> pd.DataFrame:
    """Linhas (dia, moeda) do universo point-in-time com todas as features; `target` pode ser NaN (sem janela)."""
    cols = {name: features[name].where(member).stack(future_stack=True) for name in FEATURES}
    frame = pd.DataFrame(cols)
    frame["target"] = target.where(member).stack(future_stack=True).reindex(frame.index)
    frame.index = frame.index.set_names(["timestamp", "symbol"])
    keep = member.stack(future_stack=True).reindex(frame.index).fillna(False).astype(bool)
    return frame[keep & frame[list(FEATURES)].notna().all(axis=1)]


@dataclass(frozen=True)
class Fitted:
    mean: np.ndarray       # padronização (só do treino)
    std: np.ndarray
    coef: np.ndarray       # [intercepto, w...] na escala padronizada
    iterations: int


def _sigmoid(z: np.ndarray) -> np.ndarray:
    out: np.ndarray = 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))
    return out


def fit_logistic(x: np.ndarray, y: np.ndarray, lam: float = L2_LAMBDA) -> Fitted:
    """Regressão logística L2 por Newton/IRLS. Padroniza com média e desvio de `x` (o treino)."""
    if x.ndim != 2 or len(x) != len(y) or len(y) == 0:
        raise ValueError("x (n × k) e y (n) incompatíveis ou vazios")
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std = np.where(std > 0, std, 1.0)
    z = np.column_stack([np.ones(len(x)), (x - mean) / std])
    penalty = np.full(z.shape[1], lam)
    penalty[0] = 0.0
    beta = np.zeros(z.shape[1])
    iterations = 0
    for iterations in range(1, MAX_ITER + 1):
        p = _sigmoid(z @ beta)
        grad = z.T @ (y - p) - penalty * beta
        hess = (z * (p * (1.0 - p))[:, None]).T @ z + np.diag(penalty)
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if float(np.max(np.abs(step))) < TOL:
            break
    return Fitted(mean, std, beta, iterations)


def predict(model: Fitted, x: np.ndarray) -> np.ndarray:
    """Probabilidade prevista, com a padronização congelada do treino."""
    z = np.column_stack([np.ones(len(x)), (x - model.mean) / model.std])
    return _sigmoid(z @ model.coef)


def walk_forward(
    rows: pd.DataFrame, years: tuple[int, ...], purge_days: int = PURGE_DAYS, lam: float = L2_LAMBDA
) -> tuple[pd.Series, pd.DataFrame]:
    """(probabilidade por (dia, moeda) nos anos de `years`, uma linha por dobra). Dobra `Y`: treino com dias
    <= 31/12 de `Y−1` − `purge_days` e alvo conhecido; teste = dias de `Y`."""
    days = pd.DatetimeIndex(rows.index.get_level_values("timestamp"))
    preds: list[pd.Series] = []
    folds: list[dict[str, object]] = []
    for year in years:
        cut = pd.Timestamp(f"{year - 1}-12-31", tz="UTC")
        train_end = cut - pd.Timedelta(days=purge_days)
        train = rows[(days <= train_end) & rows["target"].notna().to_numpy()]
        test = rows[days.year == year]
        if train.empty or test.empty:
            continue
        model = fit_logistic(train[list(FEATURES)].to_numpy("float64"), train["target"].to_numpy("float64"), lam)
        prob = predict(model, test[list(FEATURES)].to_numpy("float64"))
        preds.append(pd.Series(prob, index=test.index, name="prob"))
        last_day = pd.Timestamp(train.index.get_level_values("timestamp").max())
        folds.append({
            "year": year, "train_end": train_end, "last_target_end": last_day + pd.Timedelta(days=1 + TARGET_HORIZON),
            "n_train": len(train), "n_test": len(test), "positive_rate": float(train["target"].mean()),
            "iterations": model.iterations,
        })
    prob_all = pd.concat(preds) if preds else pd.Series(dtype="float64", name="prob")
    fold_frame = pd.DataFrame(folds, columns=list(FOLD_SCHEMA)).astype(FOLD_SCHEMA)
    return prob_all, fold_frame


def probability_frame(prob: pd.Series, index: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    """Probabilidades em formato largo (dia × moeda), NaN onde o modelo não previu."""
    wide = prob.unstack("symbol") if len(prob) else pd.DataFrame(index=index, columns=columns, dtype="float64")
    return wide.reindex(index=index, columns=columns).astype("float64")
