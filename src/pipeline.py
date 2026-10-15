"""Pipeline diário: extrai -> detecta -> compara com ontem -> salva histórico e publica.

Uso (da raiz do projeto):
    uv run python -m src.pipeline

Saídas:
    data/signals/history/date=YYYY-MM-DD/signals.parquet   histórico (um por dia)
    frontend/public/daily_signals.parquet                  estado atual para o frontend
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import UNIVERSE
from .extractors import BaseExtractor, BinanceAdapter, CoinGeckoMarketAdapter, ExtractorError, FearGreedAdapter
from .loaders.history_store import read_previous, write_snapshot
from .loaders.parquet_loader import write_daily_signals
from .transformers.anomaly_detector import detect
from .transformers.daily_alerts import ALERT_BUY, ALERT_EXIT, ALERT_WATCH, compare_with_previous

logger = logging.getLogger("pipeline")

BINANCE_LOOKBACK = timedelta(days=250)
FNG_LOOKBACK = timedelta(days=10)


def _optional(adapter: BaseExtractor, start: datetime | None, now: datetime) -> pd.DataFrame:
    """Fontes complementares: falha vira DataFrame vazio (o detector trata a ausência)."""
    try:
        return adapter.extract(start, now)
    except ExtractorError as exc:
        logger.warning("%s indisponível: %s", adapter.source, exc)
        return adapter.standardize(pd.DataFrame())


def run(now: datetime) -> pd.DataFrame:
    binance = BinanceAdapter(list(UNIVERSE)).extract(now - BINANCE_LOOKBACK, now)
    coingecko = _optional(CoinGeckoMarketAdapter(list(UNIVERSE.values())), None, now)
    fng = _optional(FearGreedAdapter(), now - FNG_LOOKBACK, now)

    today = detect(binance, coingecko, fng)
    if today.empty:
        raise ExtractorError("nenhum candle fechado retornado pela Binance")
    day = pd.Timestamp(today["timestamp"].max())

    final = compare_with_previous(today, read_previous(day))
    write_snapshot(final, day)
    write_daily_signals(final)
    return final


def report(df: pd.DataFrame) -> str:
    day = pd.Timestamp(df["timestamp"].max())
    lines = [f"Ciclo {day:%Y-%m-%d} · {len(df)} ativos · F&G {df['fng_value'].iloc[0]}"]
    for label in (ALERT_BUY, ALERT_WATCH, ALERT_EXIT):
        hits = df.loc[df["alert"].eq(label).fillna(False), "symbol"].tolist()
        if hits:
            lines.append(f"  {label}: {', '.join(hits)}")
    counts = df["stage"].value_counts().to_dict()
    lines.append(f"  estágios: {counts}")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        final = run(datetime.now(timezone.utc))
    except ExtractorError as exc:
        logger.error("pipeline falhou: %s", exc)
        return 1
    print(report(final))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
