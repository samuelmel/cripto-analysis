"""LEGADO — alerta informativo de pânico (reversão à média). NÃO é recomendação de compra.

Este script é anterior ao pipeline em `src/` e lê a base legada `data/raw/ohlcv` (de `extract_historical.py`).
A regra que ele aplica (z-score de 90 dias < -2,5 e RSI 14 < 30) é a antiga regra "comprar no pânico", que perdeu
dinheiro no backtest (README, "O que o backtest mostra"). Hoje, no projeto inteiro, o pânico é APENAS um aviso:
`src/transformers/anomaly_detector.py` o publica como `panic` e nenhuma camada o converte em ordem ou aporte.
Este script segue a mesma regra: lista os ativos em pânico como alerta, sem sugerir compra.

Um ativo aparece no alerta quando, na última vela fechada:
    - zscore_90 < -2.5           (preço anormalmente abaixo da média de 90 candles)
    - rsi_14 < 30                (sobrevenda)
    - histórico >= 3 anos        (filtra projetos recém-listados / mortos)
    - dados recentes             (descarta ativos deslistados ou parados)

`esticamento_sma200_pct` (0-100) = quão abaixo da SMA de 200 dias o preço está, saturando em
`CONF_SATURATION` (-50% => 100). Mede o esticamento, não a chance de reversão nem de lucro (antes se chamava
"Grau de Confiança", nome enganoso: não é confiança de nada).

Os indicadores vêm de `feature_engineering.add_features` e são calculados só para os ativos que
passam nos filtros baratos (histórico/atualidade), sobre as últimas `TAIL_ROWS` velas de cada um.

Uso:
    uv run signal_analyzer.py --data data/raw/ohlcv --exchange binance [--out data/signals/panic_YYYY-MM.parquet]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from feature_engineering import SMA_LONG, ZSCORE_WINDOW, add_features_by_symbol

ZSCORE_MAX = -2.5
RSI_MAX = 30.0
MIN_HISTORY_DAYS = 3 * 365
MAX_STALENESS_DAYS = 2
CONF_SATURATION = 0.50
# RSI de Wilder (EMA) converge em poucas centenas de velas; 500 > SMA_LONG deixa o erro desprezível.
TAIL_ROWS = max(500, SMA_LONG + ZSCORE_WINDOW)
CONF_COL = "esticamento_sma200_pct"
OUTPUT_COLUMNS = [
    "symbol", "timestamp", "close", "zscore_90", "rsi_14", "sma_200", "dist_sma_200",
    "history_days", CONF_COL,
]


def load_closes(data_dir: Path, exchange: str, timeframe: str) -> pd.DataFrame:
    """Lê só (symbol, timestamp, close) com pruning por exchange/timeframe."""
    dset = ds.dataset(data_dir, partitioning="hive")
    flt = (ds.field("exchange") == exchange) & (ds.field("timeframe") == timeframe)
    df = dset.to_table(columns=["symbol", "timestamp", "close"], filter=flt).to_pandas()
    df["symbol"] = df["symbol"].astype("category")
    return df


def find_panic_alerts(
    df: pd.DataFrame,
    *,
    zscore_max: float = ZSCORE_MAX,
    rsi_max: float = RSI_MAX,
    min_history_days: int = MIN_HISTORY_DAYS,
    max_staleness_days: int = MAX_STALENESS_DAYS,
) -> pd.DataFrame:
    """Ativos em pânico na última vela (alerta informativo, sem recomendação), do mais esticado ao menos.

    `df`: colunas symbol, timestamp (UTC), close — candles diários de vários ativos.
    """
    cols = pd.Index(OUTPUT_COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=cols)

    # Filtros baratos primeiro (1 agregação), usando o histórico completo de cada ativo.
    span = df.groupby("symbol", observed=True)["timestamp"].agg(first="min", last="max")
    span["history_days"] = (span["last"] - span["first"]).dt.days
    newest = span["last"].max()
    alive = span["last"] >= newest - pd.Timedelta(days=max_staleness_days)
    survivors = span[alive & (span["history_days"] >= min_history_days)]
    if survivors.empty:
        return pd.DataFrame(columns=cols)

    sub = df[df["symbol"].isin(survivors.index)]
    sub = sub.sort_values(["symbol", "timestamp"]).groupby("symbol", observed=True).tail(TAIL_ROWS)
    last = add_features_by_symbol(sub).groupby("symbol", observed=True).tail(1)

    hit = last[(last["zscore_90"] < zscore_max) & (last["rsi_14"] < rsi_max)].copy()
    if hit.empty:
        return pd.DataFrame(columns=cols)

    hit["history_days"] = hit["symbol"].map(survivors["history_days"]).astype(int)
    hit[CONF_COL] = (-hit["dist_sma_200"] / CONF_SATURATION).clip(0.0, 1.0) * 100.0
    hit[CONF_COL] = hit[CONF_COL].round(1)
    hit["symbol"] = hit["symbol"].astype(str).str.replace("_", "/", n=1, regex=False)
    return hit[OUTPUT_COLUMNS].sort_values(CONF_COL, ascending=False, ignore_index=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data", type=Path, default=Path("data/raw/ohlcv"))
    p.add_argument("--exchange", default="binance")
    p.add_argument("--timeframe", default="1d")
    p.add_argument("--out", type=Path, help="Salva os alertas em Parquet (ex.: data/signals/panic_2026-10.parquet)")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.timeframe != "1d":
        # Janelas de feature_engineering são em velas: SMA 200 só significa "200 dias" em 1d.
        raise SystemExit("signal_analyzer requer timeframe 1d (SMA de 200 dias e histórico em dias).")

    if args.out and args.out.suffix != ".parquet":
        # CLAUDE.md §3: Parquet em toda camada; CSV não é formato de armazenamento do projeto.
        raise SystemExit(f"--out precisa terminar em .parquet (recebido: {args.out})")

    alerts = find_panic_alerts(load_closes(args.data, args.exchange, args.timeframe))
    print("Alerta de pânico (informativo, legado): NÃO é recomendação de compra. A regra perdeu dinheiro no backtest.")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.out.with_suffix(".tmp")
        alerts.to_parquet(tmp, index=False, compression="snappy")
        tmp.replace(args.out)
        print(f"{len(alerts)} alerta(s) salvo(s) em {args.out}")
    if alerts.empty:
        print("Nenhum ativo em pânico na última vela.")
        return
    print(alerts.to_string(index=False, float_format=lambda x: f"{x:.4g}"))


if __name__ == "__main__":
    main()
