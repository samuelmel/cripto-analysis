"""Pipeline diário: atualiza a base histórica -> analisa -> compara com ontem -> publica.

Uso (da raiz do projeto):
    uv run python -m src.pipeline              atualiza a base (incremental) e analisa
    uv run python -m src.pipeline --offline    só reanalisa a base local (sem internet)
    uv run python -m src.pipeline --rebuild    baixa todo o histórico de novo desde 2017

Base local (data/market/): candles diários desde a listagem de cada par na Binance e o
Fear & Greed completo (desde 2018). A primeira execução faz o download completo.

Publica em frontend/public/:
    daily_signals.parquet   snapshot do dia com estágio e alertas
    history.parquet         histórico de preço, indicadores e estágio (gráficos)
    backtest.parquet        cada sinal histórico de COMPRAR simulado com as regras de saída
    positions.parquet       suas posições com a recomendação VENDER / SEGURAR
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import UNIVERSE
from .extractors import BaseExtractor, BinanceAdapter, CoinGeckoMarketAdapter, ExtractorError, FearGreedAdapter
from .loaders.history_store import read_previous, write_snapshot
from .loaders.market_store import (
    last_timestamp,
    read_coingecko,
    read_fng,
    read_ohlcv,
    write_coingecko,
    write_fng,
    write_ohlcv,
)
from .loaders.parquet_loader import write_daily_signals, write_parquet
from .loaders.positions_store import read_positions
from .transformers.anomaly_detector import classify_history, detect
from .transformers.daily_alerts import ALERT_BUY, ALERT_EXIT, ALERT_WATCH, compare_with_previous
from .transformers.position_advisor import ACTION_SELL, advise
from .transformers.trade_simulator import STRATEGY_SIGNAL, backtest

logger = logging.getLogger("pipeline")

HISTORY_START = datetime(2017, 1, 1, tzinfo=timezone.utc)  # Binance spot começa em 2017
PUBLIC_DIR = Path("frontend/public")


def _optional(adapter: BaseExtractor, start: datetime | None, now: datetime) -> pd.DataFrame:
    """Fontes complementares: falha vira DataFrame vazio (a análise trata a ausência)."""
    try:
        return adapter.extract(start, now)
    except ExtractorError as exc:
        logger.warning("%s indisponível: %s", adapter.source, exc)
        return adapter.standardize(pd.DataFrame())


def update_base(now: datetime, *, rebuild: bool = False) -> None:
    """Baixa só o que falta de cada ativo (ou tudo, com rebuild) e grava na base local."""
    for symbol in UNIVERSE:
        last = None if rebuild else last_timestamp(symbol)
        start = HISTORY_START if last is None else last.to_pydatetime() + timedelta(days=1)
        if start >= now - timedelta(days=1):
            continue
        candles = BinanceAdapter([symbol]).extract(start, now)
        if not candles.empty:
            write_ohlcv(candles)
            logger.info("%s: +%d candles (%s a %s)", symbol, len(candles),
                        f"{candles['timestamp'].min():%Y-%m-%d}", f"{candles['timestamp'].max():%Y-%m-%d}")

    fng = _optional(FearGreedAdapter(), None, now)
    if not fng.empty:
        write_fng(fng)
    market = _optional(CoinGeckoMarketAdapter(list(UNIVERSE.values())), None, now)
    if not market.empty:
        write_coingecko(market)


def analyze() -> dict[str, pd.DataFrame]:
    """Análise completa sobre a base local. Não acessa a rede."""
    candles = read_ohlcv(list(UNIVERSE))
    if candles.empty:
        raise ExtractorError("base local vazia: rode sem --offline para baixar o histórico")

    history = classify_history(candles, read_fng())
    today = detect(candles, read_coingecko(), read_fng(), history=history)
    day = pd.Timestamp(today["timestamp"].max())
    signals = compare_with_previous(today, read_previous(day))

    trades = backtest(history)
    open_positions = read_positions().query("not closed")
    positions = advise(open_positions, history)

    write_snapshot(signals, day)
    write_daily_signals(signals)
    write_parquet(history, PUBLIC_DIR / "history.parquet")
    write_parquet(trades, PUBLIC_DIR / "backtest.parquet")
    write_parquet(positions, PUBLIC_DIR / "positions.parquet")
    return {"signals": signals, "backtest": trades, "positions": positions}


def report(result: dict[str, pd.DataFrame]) -> str:
    signals, backtest, positions = result["signals"], result["backtest"], result["positions"]
    day = pd.Timestamp(signals["timestamp"].max())
    lines = [f"Ciclo {day:%Y-%m-%d} · {len(signals)} ativos · F&G {signals['fng_value'].iloc[0]}"]
    for label in (ALERT_BUY, ALERT_WATCH, ALERT_EXIT):
        hits = signals.loc[signals["alert"].eq(label).fillna(False), "symbol"].tolist()
        if hits:
            lines.append(f"  {label}: {', '.join(hits)}")
    lines.append(f"  estágios: {signals['stage'].value_counts().to_dict()}")

    closed = backtest[backtest["status"].eq("FECHADA")]
    for strategy, part in closed.groupby("strategy"):
        label = "sinal COMPRAR" if strategy == STRATEGY_SIGNAL else "referência semanal"
        lines.append(
            f"  backtest {label}: {len(part)} operações · acerto {part['return_pct'].gt(0).mean() * 100:.0f}% · "
            f"retorno médio {part['return_pct'].mean():+.1f}% · mediana {part['return_pct'].median():+.1f}%"
        )
    for _, p in positions.iterrows():
        tag = f"VENDER ({p['reason']})" if p["action"] == ACTION_SELL else "SEGURAR"
        lines.append(f"  posição {p['symbol']}: {p['return_pct']:+.1f}% → {tag}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline diário do crypto-analyzer")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="só reanalisa a base local")
    mode.add_argument("--rebuild", action="store_true", help="baixa todo o histórico de novo")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        if not args.offline:
            update_base(datetime.now(timezone.utc), rebuild=args.rebuild)
        result = analyze()
    except ExtractorError as exc:
        logger.error("pipeline falhou: %s", exc)
        return 1
    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
