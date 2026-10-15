"""Detector de anomalias de reversão à média: cruza Binance, CoinGecko e Fear & Greed.

Puro (CLAUDE.md §1): recebe os DataFrames padronizados dos extratores; a persistência é feita
por `src.loaders`. Sem loops Python: indicadores por ativo via groupby + rolling/ewm (cython).

Regra de compra (todas obrigatórias, NaN conta como "não atende"):
    zscore_90 < -2.5      preço 2,5 desvios abaixo da SMA de 90 dias
    rsi_14    < 30        sobrevenda
    fng_value < 25        pânico generalizado (alternative.me: 0–24 = "Extreme Fear")

Estágio (`stage`): COMPRAR se a regra acima dispara; PREPARAR (radar) se zscore_90 < -1.5 e
rsi_14 < 40, ou seja, escorregando para a zona de compra; NEUTRO nos demais casos.

`classify_history` aplica a regra a todos os dias (base do backtest); `detect` devolve só o
snapshot do dia, com market cap. Os dois usam a mesma classificação.

Tratamento de NaN:
    - candles com close nulo ou <= 0 são descartados antes dos indicadores;
    - indicadores ficam NaN até haver janela completa (90 candles para z-score, 14 para RSI);
    - desvio padrão 0 (preço constante) gera z-score NaN, não infinito;
    - o candle do dia D fecha às 00:00 de D+1: recebe o F&G publicado até esse fechamento
      (no máximo `asof_tolerance` antes); sem leitura, o F&G fica nulo e COMPRAR não dispara.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SMA_WINDOW = 90
RSI_PERIOD = 14

STAGE_BUY = "COMPRAR"
STAGE_WATCH = "PREPARAR"
STAGE_NEUTRAL = "NEUTRO"

HISTORY_SCHEMA: dict[str, str] = {
    "timestamp": "datetime64[ns, UTC]",
    "symbol": "string",
    "close": "float64",
    "sma_90": "float64",
    "zscore_90": "float64",
    "rsi_14": "float64",
    "fng_value": "Int64",
    "fng_classification": "string",
    "buy_signal": "bool",
    "stage": "string",
}

OUTPUT_SCHEMA: dict[str, str] = {
    **{k: v for k, v in HISTORY_SCHEMA.items() if k not in ("fng_value", "fng_classification", "buy_signal", "stage")},
    "market_cap_usd": "float64",
    "total_volume_usd": "float64",
    "fng_value": "Int64",
    "fng_classification": "string",
    "buy_signal": "bool",
    "stage": "string",
}


@dataclass(frozen=True)
class SignalRules:
    zscore_max: float = -2.5
    rsi_max: float = 30.0
    fng_panic_max: int = 25
    # Radar: ativo escorregando para a zona de compra, mas ainda sem disparar.
    watch_zscore_max: float = -1.5
    watch_rsi_max: float = 40.0
    # Leitura mais antiga aceita de F&G/CoinGecko em relação ao fechamento do candle.
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


def _close_time(timestamp: pd.Series) -> pd.Series:
    """Horário de fechamento do candle diário que abre em `timestamp`."""
    return timestamp + pd.Timedelta(days=1)


def classify_history(binance: pd.DataFrame, fng: pd.DataFrame, rules: SignalRules = SignalRules()) -> pd.DataFrame:
    """Indicadores + F&G + estágio para todos os dias de todos os ativos (HISTORY_SCHEMA)."""
    ind = compute_indicators(binance)
    if ind.empty:
        return _empty(HISTORY_SCHEMA)

    sentiment = (
        fng[["timestamp", "fng_value", "fng_classification"]]
        .rename(columns={"timestamp": "fng_ts"})
        .dropna(subset=["fng_ts"])
        .sort_values("fng_ts")
        if not fng.empty
        else pd.DataFrame({
            "fng_ts": pd.Series(dtype="datetime64[ns, UTC]"),
            "fng_value": pd.Series(dtype="Int64"),
            "fng_classification": pd.Series(dtype="string"),
        })
    )
    # merge_asof exige a mesma resolução temporal dos dois lados (us vs ns quebra).
    left = ind.assign(close_ts=_close_time(ind["timestamp"]).astype("datetime64[ns, UTC]")).sort_values("close_ts")
    out = pd.merge_asof(
        left,
        sentiment.astype({"fng_ts": "datetime64[ns, UTC]"}),
        left_on="close_ts",
        right_on="fng_ts",
        direction="backward",
        tolerance=rules.asof_tolerance,
    ).astype({"fng_value": "Int64", "fng_classification": "string"})

    panic = out["fng_value"].lt(rules.fng_panic_max).fillna(False).astype(bool)
    out["buy_signal"] = out["zscore_90"].lt(rules.zscore_max) & out["rsi_14"].lt(rules.rsi_max) & panic
    watch = out["zscore_90"].lt(rules.watch_zscore_max) & out["rsi_14"].lt(rules.watch_rsi_max)
    out["stage"] = np.select([out["buy_signal"], watch], [STAGE_BUY, STAGE_WATCH], STAGE_NEUTRAL)
    out["symbol"] = out["symbol"].astype("string")

    out = out[list(HISTORY_SCHEMA)].astype(HISTORY_SCHEMA)
    return out.sort_values(["symbol", "timestamp"], ignore_index=True)


def detect(
    binance: pd.DataFrame,
    coingecko: pd.DataFrame,
    fng: pd.DataFrame,
    *,
    as_of: pd.Timestamp | None = None,
    rules: SignalRules = SignalRules(),
    history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Snapshot do dia `as_of` (padrão: último candle disponível) com indicadores e estágio.

    Entradas no formato padronizado de `src.extractors`:
        binance    BinanceAdapter          (symbol "BTC/USDT")
        coingecko  CoinGeckoMarketAdapter  (symbol = ticker, "BTC"); leitura até 1 dia após o fechamento
        fng        FearGreedAdapter        (symbol "MARKET")
    `history`: resultado já calculado de `classify_history` (evita recalcular).
    Ativos sem candle no dia são omitidos. Ordenado por buy_signal e depois zscore_90 crescente.
    """
    hist = classify_history(binance, fng, rules) if history is None else history
    if hist.empty:
        return _empty(OUTPUT_SCHEMA)

    if as_of is None:
        day = hist["timestamp"].max()
    else:
        day = (as_of if as_of.tzinfo else as_of.tz_localize("UTC")).floor("D")
    snap = hist[hist["timestamp"].eq(day)]
    if snap.empty:
        return _empty(OUTPUT_SCHEMA)

    close_ts = day + pd.Timedelta(days=1)
    ts = coingecko["timestamp"]
    market = coingecko[(ts >= close_ts - rules.asof_tolerance) & (ts < close_ts + pd.Timedelta(days=1))]
    market = (
        market.sort_values("timestamp")
        .drop_duplicates("symbol", keep="last")
        .assign(base=lambda m: m["symbol"].str.upper())[["base", "market_cap_usd", "total_volume_usd"]]
    )
    out = snap.assign(base=snap["symbol"].str.split("/", n=1).str[0].str.upper()).merge(market, on="base", how="left")

    out = out[list(OUTPUT_SCHEMA)].astype(OUTPUT_SCHEMA)
    return out.sort_values(["buy_signal", "zscore_90"], ascending=[False, True], ignore_index=True)


def _empty(schema: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
