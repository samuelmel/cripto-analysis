"""Mercado sintético determinístico para a linha de base de regressão (tests/golden).

Não representa o mercado real: serve só para detectar mudanças de comportamento do código. As datas são fixas
(não dependem do relógio) e a semente é fixa, então a mesma versão do código produz sempre as mesmas saídas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

END = pd.Timestamp("2026-06-30", tz="UTC")
"""Último candle fechado do mercado sintético."""
RUN_TS = pd.Timestamp("2026-07-01 00:10", tz="UTC")
"""Momento da análise sintética: 10 minutos depois do fechamento do candle de END."""
SEED = 20261016

# símbolo -> (primeiro candle, preço inicial, beta ao fator comum, volatilidade idiossincrática diária, volume médio)
COINS: dict[str, tuple[str, float, float, float, float]] = {
    "BTC/USDT": ("2017-08-17", 4_000.0, 1.0, 0.015, 2.0e9),
    "ETH/USDT": ("2017-08-17", 300.0, 1.2, 0.022, 1.0e9),
    "ADA/USDT": ("2018-04-17", 0.25, 1.4, 0.035, 2.0e8),
    "XRP/USDT": ("2018-05-04", 0.60, 1.1, 0.035, 3.0e8),
    "DOGE/USDT": ("2019-07-05", 0.003, 1.3, 0.045, 1.5e8),
    "SOL/USDT": ("2020-08-11", 3.0, 1.5, 0.040, 4.0e8),
}

# Tendências do fator comum (drift diário) em segmentos: ciclos de alta e baixa para a regra de tendência operar.
REGIMES: tuple[tuple[str, float], ...] = (
    ("2017-08-17", 0.004),
    ("2018-01-10", -0.004),
    ("2019-01-01", 0.003),
    ("2019-07-01", -0.002),
    ("2020-03-15", 0.004),
    ("2021-11-10", -0.003),
    ("2022-12-01", 0.0025),
    ("2024-04-01", 0.0),
    ("2024-10-01", 0.002),
    ("2025-10-01", -0.002),
)
FACTOR_VOL = 0.03


def synthetic_candles() -> pd.DataFrame:
    """Candles diários no formato padronizado do BinanceAdapter, de todos os COINS até END."""
    rng = np.random.default_rng(SEED)
    days = pd.date_range(pd.Timestamp("2017-08-17", tz="UTC"), END, freq="D")
    drift = pd.Series(np.nan, index=days)
    for start, mu in REGIMES:
        drift[pd.Timestamp(start, tz="UTC")] = mu
    factor = drift.ffill().to_numpy() + rng.normal(0.0, FACTOR_VOL, len(days))

    frames = []
    for symbol, (first, price0, beta, idio, volume) in COINS.items():
        noise = rng.normal(0.0, idio, len(days))
        logret = beta * factor + noise
        listed = days >= pd.Timestamp(first, tz="UTC")
        lr = logret[listed]
        lr[0] = 0.0
        close = price0 * np.exp(np.cumsum(lr))
        opens = np.concatenate([[close[0]], close[:-1]])
        spread = np.abs(rng.normal(0.0, idio, len(close)))
        high = np.maximum(opens, close) * (1.0 + spread)
        low = np.minimum(opens, close) * (1.0 - spread)
        quote = volume * np.exp(rng.normal(0.0, 0.3, len(close)))
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": days[listed],
                    "source": "binance",
                    "symbol": symbol,
                    "open": opens,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": quote / close,
                    "quote_volume": quote,
                    "trades": 1000,
                }
            ).astype({"source": "string", "symbol": "string", "trades": "Int64"})
        )
    return pd.concat(frames, ignore_index=True)


def synthetic_fng(candles: pd.DataFrame) -> pd.DataFrame:
    """Fear & Greed sintético (formato do FearGreedAdapter), ligado ao retorno de 30 dias do BTC sintético: medo
    depois de quedas, ganância depois de altas. Publicado às 00:00 UTC, como o alternative.me."""
    btc = candles[candles["symbol"].eq("BTC/USDT")].set_index("timestamp")["close"]
    r30 = btc.pct_change(30).fillna(0.0)
    value = (50.0 + 120.0 * r30).clip(1.0, 99.0).round().astype("int64")
    labels = pd.cut(value, [0, 24, 44, 55, 75, 100], labels=["Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"])
    published = btc.index[btc.index >= pd.Timestamp("2018-02-01", tz="UTC")] + pd.Timedelta(days=1)
    return pd.DataFrame(
        {
            "timestamp": published,
            "source": "alternative_me",
            "symbol": "MARKET",
            "fng_value": value.loc[published - pd.Timedelta(days=1)].to_numpy(),
            "fng_classification": labels.loc[published - pd.Timedelta(days=1)].astype("string").to_numpy(),
        }
    ).astype({"source": "string", "symbol": "string", "fng_value": "Int64", "fng_classification": "string"})
