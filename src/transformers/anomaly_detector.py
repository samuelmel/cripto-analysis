"""Classificação diária de cada moeda: tendência de alta (regra de compra) e alerta de pânico.

Puro (CLAUDE.md §1): recebe os DataFrames padronizados dos extratores; a persistência é feita
por `src.loaders`. Sem loops Python: indicadores por ativo via groupby + rolling/ewm (cython).

Regra de compra (validada em treino 2018–2022 e teste 2023–2026, ver `research/`):
    tendência de alta = fechamento acima da SMA de 200 dias da moeda
                        E BTC com fechamento acima da sua própria SMA de 200 dias (filtro de mercado)

Estágio (`stage`), só para as moedas em `SignalRules.recommended` (padrão: BTC e ETH):
    COMPRAR    tendência de alta: comprar, ou segurar se já tem. Sai quando a condição deixa de valer
    PREPARAR   radar: fechou até 3% abaixo da SMA 200 e está subindo (perto do cruzamento)
    NEUTRO     fora da tendência, ou moeda só monitorada (sem recomendação)
    INDISPONÍVEL  dado desatualizado ou insuficiente hoje, com o motivo em `stage_reason`
                  (aplicado por `data_quality.mark_unavailable`, não por este módulo)

Alerta de pânico (`panic`), apenas informativo e SEM recomendação de compra: a regra antiga
(zscore_90 < -2.5, RSI < 30 e Fear & Greed < 25) perdeu dinheiro no backtest.

`classify_history` aplica as regras a todos os dias (base do backtest); `detect` devolve só o
snapshot do dia, com market cap. Os dois usam a mesma classificação.

Tratamento de NaN:
    - candles com close nulo ou <= 0 são descartados antes dos indicadores;
    - indicadores ficam NaN até haver janela completa (200 candles para a SMA 200, 90 para o z-score,
      14 para o RSI); NaN conta como "não atende" em toda condição;
    - desvio padrão 0 (preço constante) gera z-score NaN, não infinito;
    - o candle do dia D fecha às 00:00 de D+1: recebe o F&G publicado até esse fechamento
      (no máximo `asof_tolerance` antes); sem leitura, o F&G fica nulo e o pânico não dispara.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import RECOMMENDED, REGIME_SYMBOL

SMA_WINDOW = 90
TREND_WINDOW = 200
RSI_PERIOD = 14

STAGE_BUY = "COMPRAR"
STAGE_WATCH = "PREPARAR"
STAGE_NEUTRAL = "NEUTRO"
STAGE_UNAVAILABLE = "INDISPONÍVEL"  # sem dado confiável hoje (ver data_quality); nunca é gerado por classify_history

HISTORY_SCHEMA: dict[str, str] = {
    "timestamp": "datetime64[ns, UTC]",
    "symbol": "string",
    "close": "float64",
    "sma_90": "float64",
    "zscore_90": "float64",
    "sma_200": "float64",
    "rsi_14": "float64",
    "fng_value": "Int64",
    "fng_classification": "string",
    "regime_up": "bool",   # BTC acima da SMA 200 neste dia
    "uptrend": "bool",     # moeda acima da SMA 200 E regime_up
    "panic": "bool",       # alerta de pânico (informativo)
    "stage": "string",
}

_SNAPSHOT_TAIL = ("fng_value", "fng_classification", "regime_up", "uptrend", "panic", "stage")
OUTPUT_SCHEMA: dict[str, str] = {
    **{k: v for k, v in HISTORY_SCHEMA.items() if k not in _SNAPSHOT_TAIL},
    "market_cap_usd": "float64",
    "total_volume_usd": "float64",
    **{k: v for k, v in HISTORY_SCHEMA.items() if k in _SNAPSHOT_TAIL},
    "stage_reason": "string",  # motivo do INDISPONÍVEL; nulo nos demais estágios
}


@dataclass(frozen=True)
class SignalRules:
    recommended: tuple[str, ...] = RECOMMENDED
    regime_symbol: str = REGIME_SYMBOL
    # Radar: até esta distância abaixo da SMA 200 e subindo há `rising_days` dias.
    watch_distance: float = 0.03
    rising_days: int = 5
    # Alerta de pânico (informativo).
    zscore_max: float = -2.5
    rsi_max: float = 30.0
    fng_panic_max: int = 25
    # Leitura mais antiga aceita de F&G/CoinGecko em relação ao fechamento do candle.
    asof_tolerance: pd.Timedelta = pd.Timedelta(days=1)


def compute_indicators(binance: pd.DataFrame) -> pd.DataFrame:
    """Histórico com sma_90, zscore_90, sma_200 e rsi_14 por ativo. Uma linha por (symbol, dia)."""
    df = binance.loc[binance["close"].gt(0) & np.isfinite(binance["close"].to_numpy(dtype="float64")), ["timestamp", "symbol", "close"]]
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

    trend = close.rolling(TREND_WINDOW, min_periods=TREND_WINDOW).mean().droplevel(0)

    return df.assign(
        sma_90=sma,
        sma_200=trend,
        zscore_90=(df["close"] - sma) / std.replace(0.0, np.nan),
        rsi_14=rsi,
    )


def _wilder_mean(values: pd.Series, keys: pd.Series) -> pd.Series:
    """Média de Wilder por ativo (EMA com alpha = 1/RSI_PERIOD), alinhada ao índice de `values`."""
    grouped = values.groupby(keys, observed=True, sort=False)
    return grouped.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean().droplevel(0)


def _with_trend(ind: pd.DataFrame, rules: SignalRules) -> pd.DataFrame:
    """Acrescenta `regime_up` (BTC acima da SMA 200 no dia) e `uptrend` (moeda E regime em alta)."""
    above = ind["close"].gt(ind["sma_200"])
    regime_days = ind.loc[above & ind["symbol"].eq(rules.regime_symbol), "timestamp"]
    regime_up = ind["timestamp"].isin(regime_days)
    return ind.assign(regime_up=regime_up, uptrend=above & regime_up)


def _stage(out: pd.DataFrame, rules: SignalRules) -> pd.Series:
    """COMPRAR / PREPARAR / NEUTRO. Só as moedas `recommended` saem de NEUTRO."""
    recommended = out["symbol"].isin(list(rules.recommended))
    rising = out["close"].gt(out.groupby("symbol", observed=True)["close"].shift(rules.rising_days))
    gap = out["close"] / out["sma_200"] - 1.0
    # Se cruzar a SMA 200, a moeda só entra em COMPRAR com o BTC em alta (o BTC é o próprio filtro).
    regime_ok = out["regime_up"] | out["symbol"].eq(rules.regime_symbol)
    near = ~out["uptrend"] & gap.lt(0.0) & gap.ge(-rules.watch_distance) & rising & regime_ok
    return pd.Series(
        np.select([recommended & out["uptrend"], recommended & near], [STAGE_BUY, STAGE_WATCH], STAGE_NEUTRAL),
        index=out.index,
    )


def _close_time(timestamp: pd.Series) -> pd.Series:
    """Horário de fechamento do candle diário que abre em `timestamp`."""
    return timestamp + pd.Timedelta(days=1)


def classify_history(binance: pd.DataFrame, fng: pd.DataFrame, rules: SignalRules = SignalRules()) -> pd.DataFrame:
    """Indicadores + F&G + estágio para todos os dias de todos os ativos (HISTORY_SCHEMA)."""
    ind = _with_trend(compute_indicators(binance), rules)
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
    out["panic"] = out["zscore_90"].lt(rules.zscore_max) & out["rsi_14"].lt(rules.rsi_max) & panic
    out["symbol"] = out["symbol"].astype("string")
    out["stage"] = _stage(out, rules)

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
    Sem `as_of`, cada moeda entra com o seu último candle (a desatualizada é marcada por `data_quality`); com `as_of`, ativos sem candle no dia são omitidos. Ordenado por símbolo (a ordem de exibição vem de `daily_alerts`).
    """
    hist = classify_history(binance, fng, rules) if history is None else history
    if hist.empty:
        return _empty(OUTPUT_SCHEMA)

    if as_of is None:
        day = hist["timestamp"].max()
        snap = hist.sort_values(["symbol", "timestamp"]).groupby("symbol", sort=False).tail(1)  # último candle de cada moeda
    else:
        day = (as_of if as_of.tzinfo else as_of.tz_localize("UTC")).floor("D")
        snap = hist[hist["timestamp"].eq(day)]
    if snap.empty:
        return _empty(OUTPUT_SCHEMA)

    close_ts = day + pd.Timedelta(days=1)
    if coingecko.empty:  # fonte secundária fora do ar e sem base local: market cap fica nulo
        market = pd.DataFrame({"base": pd.Series(dtype="string"), "market_cap_usd": pd.Series(dtype="float64"),
                               "total_volume_usd": pd.Series(dtype="float64")})
    else:
        ts = coingecko["timestamp"]
        market = coingecko[(ts >= close_ts - rules.asof_tolerance) & (ts < close_ts + pd.Timedelta(days=1))]
        market = (
            market.sort_values("timestamp")
            .drop_duplicates("symbol", keep="last")
            .assign(base=lambda m: m["symbol"].str.upper())[["base", "market_cap_usd", "total_volume_usd"]]
        )
    out = snap.assign(base=snap["symbol"].str.split("/", n=1).str[0].str.upper(), stage_reason=pd.Series(pd.NA, index=snap.index, dtype="string")).merge(
        market.astype({"base": "string"}), on="base", how="left"
    )

    out = out[list(OUTPUT_SCHEMA)].astype(OUTPUT_SCHEMA)
    return out.sort_values("symbol", ignore_index=True)


def _empty(schema: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
