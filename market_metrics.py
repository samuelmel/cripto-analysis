"""Métricas de desempenho por ativo a partir dos closes diários (pandas puro, sem UI).

Entrada: DataFrame wide — índice `timestamp` (UTC, diário), colunas = símbolos, valores = close.
Use `to_wide` para converter o formato longo de `signal_analyzer.load_closes`.
"""

from __future__ import annotations

import pandas as pd

ALIVE_DAYS = 2  # ativo sem candle nos últimos N dias é considerado deslistado/parado


def to_wide(closes: pd.DataFrame) -> pd.DataFrame:
    """(symbol, timestamp, close) em formato longo -> wide, com símbolos no formato BASE/QUOTE."""
    wide = closes.pivot(index="timestamp", columns="symbol", values="close")
    wide.columns = wide.columns.astype(str).str.replace("_", "/", n=1, regex=False)
    return wide.sort_index()


def _ret(s: pd.Series, ref: pd.Timestamp, base_date: pd.Timestamp) -> float:
    """Retorno do último close até `ref` em relação ao último close até `base_date`."""
    base = s[s.index <= base_date]
    if base.empty:
        return float("nan")
    return s.iloc[-1] / base.iloc[-1] - 1.0


def summarize(wide: pd.DataFrame, ref: pd.Timestamp | None = None) -> pd.DataFrame:
    """Uma linha por ativo ativo em `ref` com retornos, dias sem queda e drawdown de 1 ano.

    Colunas:
        preco          último close
        ret_mes        retorno desde o fechamento do mês anterior (mês corrente em `ref`)
        ret_3m         retorno nos últimos 90 dias
        ret_1a         retorno nos últimos 365 dias
        max_dd_1a      pior queda desde um topo, nos últimos 365 dias (valor <= 0)
        dias_sem_queda dias desde o último dia em que o close caiu em relação ao anterior
        dias_historico dias entre o primeiro e o último candle
    """
    ref = wide.index.max() if ref is None else ref
    month_start = ref.replace(day=1)
    rows = {}
    for sym in wide.columns:
        s = wide[sym].dropna()
        s = s[s.index <= ref]
        if s.empty or (ref - s.index[-1]).days > ALIVE_DAYS:
            continue

        drops = s.index[s.diff() < 0]
        window = s[s.index > ref - pd.Timedelta(days=365)]
        drawdown = window / window.cummax() - 1.0
        rows[sym] = {
            "preco": s.iloc[-1],
            "ret_mes": _ret(s, ref, month_start - pd.Timedelta(days=1)),
            "ret_3m": _ret(s, ref, ref - pd.Timedelta(days=90)),
            "ret_1a": _ret(s, ref, ref - pd.Timedelta(days=365)),
            "max_dd_1a": drawdown.min() if not drawdown.empty else float("nan"),
            "dias_sem_queda": (ref - drops[-1]).days if len(drops) else (ref - s.index[0]).days,
            "dias_historico": (s.index[-1] - s.index[0]).days,
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def normalized(wide: pd.DataFrame, symbols: list[str], start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Preço em base 100 no início de cada série (ou em `start`), para comparar moedas de preços diferentes."""
    sub = wide[symbols]
    if start is not None:
        sub = sub[sub.index >= start]
    out = {}
    for sym in sub.columns:
        s = sub[sym].dropna()
        if not s.empty:
            out[sym] = s / s.iloc[0] * 100.0
    return pd.DataFrame(out)


def monthly_returns(wide: pd.DataFrame, months: int = 24) -> pd.DataFrame:
    """Retorno de cada mês (fechamento do mês / fechamento do mês anterior - 1). Último mês pode ser parcial."""
    month_end = wide.resample("ME").last()
    return month_end.pct_change(fill_method=None).tail(months)
