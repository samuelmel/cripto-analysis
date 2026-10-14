"""Detector de anomalias de reversão à média: cruza Binance, CoinGecko e Fear & Greed.

Puro (CLAUDE.md §1): recebe os DataFrames padronizados dos extratores e devolve o snapshot do
dia; a persistência é feita por `src.loaders`. Sem loops Python: indicadores por ativo via
groupby + rolling/ewm (cython).

Regra de compra (todas obrigatórias, NaN conta como "não atende"):
    zscore_90 < -2.5      preço 2,5 desvios abaixo da SMA de 90 dias
    rsi_14    < 30        sobrevenda
    fng_value < 25        pânico generalizado (alternative.me: 0–24 = "Extreme Fear")

Tratamento de NaN:
    - candles com close nulo ou <= 0 são descartados antes dos indicadores;
    - indicadores ficam NaN até haver janela completa (90 candles para z-score, 14 para RSI);
    - desvio padrão 0 (preço constante) gera z-score NaN, não infinito;
    - CoinGecko e Fear & Greed usam a última observação em até `asof_tolerance` antes do dia;
      sem observação, as colunas ficam nulas e, para o F&G, o sinal não dispara.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SMA_WINDOW = 90
RSI_PERIOD = 14

OUTPUT_SCHEMA: dict[str, str] = {
    "timestamp": "datetime64[ns, UTC]",
    "symbol": "string",
    "close": "float64",
    "sma_90": "float64",
    "zscore_90": "float64",
    "rsi_14": "float64",
    "market_cap_usd": "float64",
    "total_volume_usd": "float64",
    "fng_value": "Int64",
    "fng_classification": "string",
    "buy_signal": "bool",
}


@dataclass(frozen=True)
class SignalRules:
    zscore_max: float = -2.5
    rsi_max: float = 30.0
    fng_panic_max: int = 25
    asof_tolerance: pd.Timedelta = pd.Timedelta(days=1)


def compute_indicators(binance: pd.DataFrame) -> pd.DataFrame:
    """Histórico com sma_90, zscore_90 e rsi_14 por ativo. Uma linha por (symbol, dia)."""
    df = binance.loc[binance["close"].gt(0), ["timestamp", "symbol", "close"]]
    df = df.assign(
        timestamp=df["timestamp"].dt.floor("D"),
        symbol=df["symbol"].astype("category"),
    )
    df = df.drop_duplicates(["symbol", "timestamp"], keep="last")
    df = df.sort_values(["symbol", "timestamp"], ignore_index=True)

    keys = df["symbol"]
    close = df.groupby(keys, observed=True, sort=False)["close"]
    window = close.rolling(SMA_WINDOW, min_periods=SMA_WINDOW)
    sma = window.mean().droplevel(0)
    std = window.std(ddof=0).droplevel(0)

    delta = close.diff()
    avg_gain = _wilder_mean(delta.clip(lower=0.0), keys)
    avg_loss = _wilder_mean((-delta).clip(lower=0.0), keys)
    rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss.replace(0.0, np.nan))
    rsi = rsi.mask(avg_loss.eq(0.0) & avg_gain.notna(), 100.0)  # sem perdas na janela => 100

    return df.assign(
        sma_90=sma,
        zscore_90=(df["close"] - sma) / std.replace(0.0, np.nan),
        rsi_14=rsi,
    )


def _wilder_mean(values: pd.Series, keys: pd.Series) -> pd.Series:
    """Média de Wilder por ativo (EMA com alpha = 1/RSI_PERIOD), alinhada ao índice de `values`."""
    grouped = values.groupby(keys, observed=True, sort=False)
    return grouped.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean().droplevel(0)


def _latest_within(df: pd.DataFrame, day: pd.Timestamp, tolerance: pd.Timedelta) -> pd.DataFrame:
    """Linhas com timestamp em [day - tolerance, day + 1d), última por symbol."""
    ts = df["timestamp"]
    recent = df[(ts >= day - tolerance) & (ts < day + pd.Timedelta(days=1))]
    return recent.sort_values("timestamp").drop_duplicates("symbol", keep="last")


def detect(
    binance: pd.DataFrame,
    coingecko: pd.DataFrame,
    fng: pd.DataFrame,
    *,
    as_of: pd.Timestamp | None = None,
    rules: SignalRules = SignalRules(),
) -> pd.DataFrame:
    """Snapshot do dia `as_of` (padrão: último candle disponível) com indicadores e `buy_signal`.

    Entradas no formato padronizado de `src.extractors`:
        binance    BinanceAdapter          (symbol "BTC/USDT")
        coingecko  CoinGeckoMarketAdapter  (symbol = ticker, "BTC")
        fng        FearGreedAdapter        (symbol "MARKET")
    Ativos sem candle no dia são omitidos. Ordenado por buy_signal e depois zscore_90 crescente.
    """
    ind = compute_indicators(binance)
    if ind.empty:
        return _empty()

    if as_of is None:
        day = ind["timestamp"].max()
    else:
        day = (as_of if as_of.tzinfo else as_of.tz_localize("UTC")).floor("D")
    snap = ind[ind["timestamp"].eq(day)]
    if snap.empty:
        return _empty()

    market = _latest_within(coingecko, day, rules.asof_tolerance)
    market = market.assign(base=market["symbol"].str.upper())[["base", "market_cap_usd", "total_volume_usd"]]
    snap = snap.assign(
        symbol=snap["symbol"].astype("string"),
        base=snap["symbol"].astype("string").str.split("/", n=1).str[0].str.upper(),
    ).merge(market, on="base", how="left")

    # Exatamente 1 linha: a leitura mais recente do F&G, ou nulos se não houver (reindex preenche NA).
    sentiment = (
        _latest_within(fng, day, rules.asof_tolerance)
        .tail(1)[["fng_value", "fng_classification"]]
        .reset_index(drop=True)
        .reindex([0])
    )
    out = snap.merge(sentiment, how="cross").astype({"fng_value": "Int64", "fng_classification": "string"})
    panic = out["fng_value"].lt(rules.fng_panic_max).fillna(False).astype(bool)
    out["buy_signal"] = out["zscore_90"].lt(rules.zscore_max) & out["rsi_14"].lt(rules.rsi_max) & panic

    out = out[list(OUTPUT_SCHEMA)].astype(OUTPUT_SCHEMA)
    return out.sort_values(["buy_signal", "zscore_90"], ascending=[False, True], ignore_index=True)


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in OUTPUT_SCHEMA.items()})
