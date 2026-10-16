"""LEGADO — indicadores técnicos sobre a base data/raw (usado só por signal_analyzer.py).

O pipeline vigente calcula os próprios indicadores em src/transformers/ (anomaly_detector, selection).

Input: DataFrame OHLCV da etapa de extração (colunas: timestamp, open, high, low, close, volume),
ordenado ou não por timestamp. Para vários ativos, use `add_features_by_symbol`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RSI_PERIOD = 14
BB_WINDOW = 20
BB_STD = 2.0
SMA_SHORT = 50
SMA_LONG = 200
ZSCORE_WINDOW = 90


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """RSI de Wilder (média móvel exponencial com alpha=1/period)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # Sem perdas na janela => RSI = 100 (e não NaN); mantém NaN no período de aquecimento.
    return out.where(~((avg_loss == 0.0) & avg_gain.notna()), 100.0)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona indicadores a um único ativo. Retorna cópia ordenada por timestamp."""
    out = df.sort_values("timestamp").reset_index(drop=True)
    close = out["close"]

    out["rsi_14"] = rsi(close)

    bb_mid = close.rolling(BB_WINDOW).mean()
    bb_std = close.rolling(BB_WINDOW).std(ddof=0)
    out["bb_mid"] = bb_mid
    out["bb_upper"] = bb_mid + BB_STD * bb_std
    out["bb_lower"] = bb_mid - BB_STD * bb_std
    band_width = out["bb_upper"] - out["bb_lower"]
    out["bb_pct_b"] = (close - out["bb_lower"]) / band_width.replace(0.0, np.nan)
    out["bb_bandwidth"] = band_width / bb_mid

    out["sma_50"] = close.rolling(SMA_SHORT).mean()
    out["sma_200"] = close.rolling(SMA_LONG).mean()
    out["dist_sma_200"] = close / out["sma_200"] - 1.0

    z_mean = close.rolling(ZSCORE_WINDOW).mean()
    z_std = close.rolling(ZSCORE_WINDOW).std(ddof=0)
    out["zscore_90"] = (close - z_mean) / z_std.replace(0.0, np.nan)

    return out


GROUP_COLS = ["exchange", "timeframe", "symbol"]
OHLCV_COLS = ["timestamp", "open", "high", "low", "close", "volume"]

logger = logging.getLogger("feature_engineering")


def add_features_by_symbol(df: pd.DataFrame, group_cols: list[str] = GROUP_COLS) -> pd.DataFrame:
    """Aplica `add_features` por ativo/timeframe, sem vazar janelas rolantes entre eles."""
    parts = [add_features(g) for _, g in df.groupby(group_cols, sort=True, observed=True)]
    return pd.concat(parts, ignore_index=True)


def load_all(root: Path) -> pd.DataFrame:
    """Lê todo o dataset Parquet particionado (todas as exchanges, símbolos e datas)."""
    df = pd.read_parquet(root)
    for col in GROUP_COLS:
        df[col] = df[col].astype(str)
    df["symbol"] = df["symbol"].str.replace("_", "/", n=1, regex=False)
    return df[GROUP_COLS + OHLCV_COLS].drop_duplicates(GROUP_COLS + ["timestamp"])


def main() -> int:
    p = argparse.ArgumentParser(description="LEGADO: recalcula indicadores para todo o dataset data/raw e grava em Parquet.")
    p.add_argument("--input", type=Path, default=Path("data/raw/ohlcv"))
    p.add_argument("--output", type=Path, default=Path("data/features/features.parquet"))
    p.add_argument("--parquet", action="store_true", help="obsoleto e ignorado: a saída já é sempre Parquet")
    a = p.parse_args()
    logging.basicConfig(level="INFO", format="%(asctime)s | %(levelname)-8s | %(message)s", stream=sys.stdout)

    if a.output.suffix != ".parquet":
        # CLAUDE.md §3: Parquet em toda camada (antes este script gravava CSV).
        logger.error("--output precisa terminar em .parquet (recebido: %s)", a.output)
        return 1
    if not a.input.exists():
        logger.error("entrada não encontrada: %s (rode extract_historical.py antes)", a.input)
        return 1
    raw = load_all(a.input)
    logger.info("lidas %d linhas de %d séries", len(raw), raw.groupby(GROUP_COLS).ngroups)

    out = add_features_by_symbol(raw)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.output.with_suffix(".tmp")
    out.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(a.output)  # escrita atômica: o arquivo nunca fica pela metade
    logger.info("features gravadas: %s (%d linhas, %s a %s)", a.output, len(out), out["timestamp"].min(), out["timestamp"].max())
    return 0


if __name__ == "__main__":
    sys.exit(main())
