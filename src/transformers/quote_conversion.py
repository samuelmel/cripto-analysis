"""Pares cotados em BTC convertidos para USDT, para ampliar o histórico com dados reais da Binance.

Puro (CLAUDE.md §1). Muitas moedas negociaram contra BTC antes de ganhar par em USDT (ou nunca ganharam). O preço em
dólar do dia sai do próprio arquivo oficial: preço em BTC × preço do BTC em USDT no mesmo dia.

Conversão (`to_usdt`), por dia, com o candle do BTC/USDT do mesmo dia:
    abertura   abertura_BTC × abertura do BTCUSDT
    fechamento fechamento_BTC × fechamento do BTCUSDT
    máxima     máximo(abertura, fechamento, máxima_BTC × fechamento do BTCUSDT)   (aproximação: a hora da máxima
    mínima     mínimo(abertura, fechamento, mínima_BTC × fechamento do BTCUSDT)    nos dois pares não é conhecida)
    volume     volume em BTC × fechamento do BTCUSDT (aproximação do volume em dólar)
Dia sem candle do BTCUSDT: sem conversão (nada é inventado).

Emenda (`splice`): para cada moeda, os candles em USDT valem sempre que existem; os convertidos só entram ANTES do
primeiro candle em USDT da moeda (ou sempre, se ela nunca teve par em USDT). O símbolo continua `BASE/USDT` e a coluna
`source` diz de onde veio cada candle.
"""

from __future__ import annotations

import pandas as pd

SOURCE_CONVERTED = "binance_btc_convertido"


def to_usdt(btc_pairs: pd.DataFrame, btc_usdt: pd.DataFrame) -> pd.DataFrame:
    """Candles de pares `BASE/BTC` -> `BASE/USDT` pelo BTCUSDT do mesmo dia."""
    if btc_pairs.empty or btc_usdt.empty:
        return btc_pairs.iloc[0:0]
    ref = (btc_usdt.assign(day=btc_usdt["timestamp"].dt.floor("D"))
           .drop_duplicates("day", keep="last").set_index("day")[["open", "close"]])
    c = btc_pairs.assign(day=btc_pairs["timestamp"].dt.floor("D"))
    c = c[c["day"].isin(ref.index)]
    bo = ref["open"].reindex(c["day"]).to_numpy()
    bc = ref["close"].reindex(c["day"]).to_numpy()
    open_usd = c["open"].to_numpy() * bo
    close_usd = c["close"].to_numpy() * bc
    high_usd = pd.concat([pd.Series(open_usd), pd.Series(close_usd), pd.Series(c["high"].to_numpy() * bc)], axis=1).max(axis=1)
    low_usd = pd.concat([pd.Series(open_usd), pd.Series(close_usd), pd.Series(c["low"].to_numpy() * bc)], axis=1).min(axis=1)
    out = pd.DataFrame({
        "symbol": c["symbol"].astype(str).str.replace("/BTC", "/USDT", regex=False).to_numpy(),
        "timestamp": c["timestamp"].to_numpy(),
        "open": open_usd, "high": high_usd.to_numpy(), "low": low_usd.to_numpy(), "close": close_usd,
        "volume": c["volume"].to_numpy(), "quote_volume": c["quote_volume"].to_numpy() * bc,
        "source": SOURCE_CONVERTED,
    })
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    return out.dropna(subset=["open", "close"]).reset_index(drop=True)


def splice(usdt: pd.DataFrame, converted: pd.DataFrame) -> pd.DataFrame:
    """Candles em USDT mais os convertidos de antes do primeiro candle em USDT de cada moeda."""
    if converted.empty:
        return usdt
    first = usdt.groupby("symbol")["timestamp"].min()
    start = converted["symbol"].map(first)
    before = converted[start.isna() | (converted["timestamp"] < start)]
    cols = [c for c in usdt.columns if c in before.columns]
    extra = before[cols]
    return pd.concat([usdt, extra], ignore_index=True).sort_values(["symbol", "timestamp"], ignore_index=True)
