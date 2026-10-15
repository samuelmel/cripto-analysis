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
    backtest.parquet        cada operação histórica da regra de tendência (BTC e ETH)
    performance.parquet     carteira: tendência x comprar e segurar x pânico, em treino e teste
    positions.parquet       suas posições com a recomendação VENDER / SEGURAR
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import FEE_PER_SIDE, RECOMMENDED, TEST_PERIOD, TRAIN_PERIOD, UNIVERSE
from .extractors import MARKET_SYMBOL, BaseExtractor, BinanceAdapter, CoinGeckoMarketAdapter, ExtractorError, FearGreedAdapter
from .loaders.history_store import read_previous, write_snapshot
from .loaders.market_store import (
    MixedSourceError,
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
from .loaders.source_log import write_source_log
from .transformers.anomaly_detector import classify_history, detect
from .transformers.data_quality import audit_candles, availability, clean_candles, mark_unavailable
from .transformers.daily_alerts import ALERT_BUY, ALERT_EXIT, ALERT_SELL, ALERT_WATCH, compare_with_previous
from .transformers.position_advisor import ACTION_SELL, ACTION_UNAVAILABLE, advise, realized
from .transformers.universe import select_universe
from .transformers.trade_simulator import (
    PERIOD_TEST,
    PERIOD_TRAIN,
    STRATEGY_HOLD,
    STRATEGY_TREND,
    backtest,
    performance_summary,
)

logger = logging.getLogger("pipeline")

HISTORY_START = datetime(2017, 1, 1, tzinfo=timezone.utc)  # Binance spot começa em 2017
PUBLIC_DIR = Path("frontend/public")

PERIODS: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
    PERIOD_TRAIN: (pd.Timestamp(TRAIN_PERIOD[0], tz="UTC"), pd.Timestamp(TRAIN_PERIOD[1], tz="UTC")),
    PERIOD_TEST: (pd.Timestamp(TEST_PERIOD[0], tz="UTC"), pd.Timestamp(TEST_PERIOD[1], tz="UTC")),
}


def _event(source: str, scope: str, now: datetime, error: str | None, frame: pd.DataFrame) -> dict[str, object]:
    """Uma linha do registro de fontes: o que aconteceu na atualização de `scope` por `source`."""
    return {
        "source": source,
        "scope": scope,
        "updated_at": pd.Timestamp(now),
        "status": "ok" if error is None else "erro",
        "rows": len(frame),
        "last_data_ts": frame["timestamp"].max() if not frame.empty else pd.NaT,
        "detail": error or "",
    }


def _optional(adapter: BaseExtractor, start: datetime | None, now: datetime) -> tuple[pd.DataFrame, str | None]:
    """Fontes complementares: falha vira DataFrame vazio e a mensagem do erro (a análise trata a ausência)."""
    try:
        return adapter.extract(start, now), None
    except ExtractorError as exc:
        logger.warning("%s indisponível: %s", adapter.source, exc)
        return adapter.standardize(pd.DataFrame()), str(exc)


def update_base(now: datetime, *, rebuild: bool = False) -> pd.DataFrame:
    """Baixa só o que falta de cada ativo (ou tudo, com rebuild) e grava na base local.

    Falha de uma fonte não derruba o pipeline: vai para o registro de fontes e a moeda sem dado novo
    fica desatualizada (INDISPONÍVEL na análise). Devolve o registro desta execução.
    """
    events: list[dict[str, object]] = []
    for symbol in UNIVERSE:
        last = None if rebuild else last_timestamp(symbol)
        start = HISTORY_START if last is None else last.to_pydatetime() + timedelta(days=1)
        if start >= now - timedelta(days=1):
            continue
        candles = pd.DataFrame()
        error: str | None = None
        try:
            candles = BinanceAdapter([symbol]).extract(start, now)
            if not candles.empty:
                write_ohlcv(candles)
                logger.info("%s: +%d candles (%s a %s)", symbol, len(candles),
                            f"{candles['timestamp'].min():%Y-%m-%d}", f"{candles['timestamp'].max():%Y-%m-%d}")
        except (ExtractorError, MixedSourceError) as exc:
            error = str(exc)
            logger.error("%s: atualização falhou: %s", symbol, exc)
        events.append(_event(BinanceAdapter.source, symbol, now, error, candles))

    fng, fng_error = _optional(FearGreedAdapter(), None, now)
    if not fng.empty:
        write_fng(fng)
    events.append(_event(FearGreedAdapter.source, MARKET_SYMBOL, now, fng_error, fng))
    market, market_error = _optional(CoinGeckoMarketAdapter(list(UNIVERSE.values())), None, now)
    if not market.empty:
        write_coingecko(market)
    events.append(_event(CoinGeckoMarketAdapter.source, MARKET_SYMBOL, now, market_error, market))

    log = pd.DataFrame(events)
    write_source_log(log)
    return log


def analyze(today: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Análise completa sobre a base local. Não acessa a rede. `today` é a data de referência (injetada)."""
    raw = read_ohlcv(list(UNIVERSE))
    if raw.empty:
        raise ExtractorError("base local vazia: rode sem --offline para baixar o histórico")

    selection = select_universe(UNIVERSE, raw)
    kept = raw[raw["symbol"].isin(selection.kept)]
    issues = audit_candles(kept)
    candles = clean_candles(kept)
    fng = read_fng()

    history = classify_history(candles, fng)
    available = availability(history, selection.kept, today)
    snapshot = mark_unavailable(detect(candles, read_coingecko(), fng, history=history), available)
    day = pd.Timestamp(snapshot["timestamp"].max())
    # O dia anterior vem do próprio histórico recalculado: o alerta segue a regra atual mesmo que
    # os snapshots antigos em data/signals tenham sido gerados por uma regra diferente.
    previous = history[history["timestamp"].eq(day - pd.Timedelta(days=1))]
    signals = compare_with_previous(snapshot, previous if not previous.empty else read_previous(day))

    trades = backtest(history, RECOMMENDED)
    performance = performance_summary(
        history, {"PRINCIPAIS": RECOMMENDED, "TODAS": selection.kept}, PERIODS, FEE_PER_SIDE
    )
    positions = _publish_positions(history, available)

    write_snapshot(signals, day)
    write_daily_signals(signals)
    write_parquet(history, PUBLIC_DIR / "history.parquet")
    write_parquet(trades, PUBLIC_DIR / "backtest.parquet")
    write_parquet(performance, PUBLIC_DIR / "performance.parquet")
    dropped = pd.DataFrame({"symbol": list(selection.dropped), "reason": list(selection.dropped.values())})
    return {
        "signals": signals, "backtest": trades, "performance": performance, "positions": positions,
        "availability": available, "issues": issues, "dropped": dropped,
    }


def _publish_positions(history: pd.DataFrame, available: pd.DataFrame) -> pd.DataFrame:
    stored = read_positions()
    positions = advise(stored[~stored["closed"]], history, available=available)
    write_parquet(positions, PUBLIC_DIR / "positions.parquet")
    write_parquet(realized(stored[stored["closed"]]), PUBLIC_DIR / "closed_positions.parquet")
    return positions


def refresh_positions(now: datetime) -> pd.DataFrame:
    """Só reavalia e publica as posições (usado após registrar compra/venda). Sem rede, sem backtest."""
    raw = read_ohlcv(list(UNIVERSE))
    if raw.empty:
        raise ExtractorError("base local vazia: rode o pipeline completo antes")
    selection = select_universe(UNIVERSE, raw)
    candles = clean_candles(raw[raw["symbol"].isin(selection.kept)])
    history = classify_history(candles, read_fng())
    return _publish_positions(history, availability(history, selection.kept, pd.Timestamp(now)))


def report(result: dict[str, pd.DataFrame], source_errors: pd.DataFrame | None = None) -> str:
    signals, trades, performance, positions = result["signals"], result["backtest"], result["performance"], result["positions"]
    day = pd.Timestamp(signals["timestamp"].max())
    lines = [f"Ciclo {day:%Y-%m-%d} · {len(signals)} ativos · F&G {signals['fng_value'].iloc[0]}"]
    for _, e in (source_errors if source_errors is not None else pd.DataFrame()).iterrows():
        lines.append(f"  AVISO fonte {e['source']} ({e['scope']}): {e['detail']}")
    for _, d in result["dropped"].iterrows():
        lines.append(f"  fora da análise {d['symbol']}: {d['reason']}")
    for _, u in result["availability"].loc[lambda a: ~a["available"]].iterrows():
        lines.append(f"  INDISPONÍVEL {u['symbol']}: {u['reason']}")
    for _, q in result["issues"].iterrows():
        lines.append(f"  qualidade {q['symbol']}: {q['kind']} ({q['count']}) {q['detail']}")
    for label in (ALERT_BUY, ALERT_SELL, ALERT_WATCH, ALERT_EXIT):
        hits = signals.loc[signals["alert"].eq(label).fillna(False), "symbol"].tolist()
        if hits:
            lines.append(f"  {label}: {', '.join(hits)}")
    lines.append(f"  estágios: {signals['stage'].value_counts().to_dict()}")
    panic = signals.loc[signals["panic"], "symbol"].tolist()
    if panic:
        lines.append(f"  mercado em pânico (só alerta, sem recomendação): {', '.join(panic)}")

    closed = trades[trades["status"].eq("FECHADA")]
    lines.append(
        f"  operações da tendência (BTC/ETH): {len(closed)} fechadas · acerto {closed['return_pct'].gt(0).mean() * 100:.0f}% · "
        f"retorno médio {closed['return_pct'].mean():+.1f}%"
    )
    main = performance[performance["universe"].eq("PRINCIPAIS") & performance["strategy"].isin([STRATEGY_TREND, STRATEGY_HOLD])]
    for _, r in main.iterrows():
        lines.append(
            f"  carteira BTC+ETH {r['period'].lower()} · {r['strategy']}: {r['total_return_pct']:+.1f}% "
            f"({r['annual_return_pct']:+.1f}%/ano) · pior queda {r['max_drawdown_pct']:.1f}%"
        )
    for _, p in positions.iterrows():
        if p["action"] == ACTION_UNAVAILABLE:
            tag = f"INDISPONÍVEL ({p['data_note']})"
        else:
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
    now = datetime.now(timezone.utc)
    try:
        failures = pd.DataFrame()
        if not args.offline:
            log = update_base(now, rebuild=args.rebuild)
            failures = log[log["status"].eq("erro")]
        result = analyze(pd.Timestamp(now))
    except ExtractorError as exc:
        logger.error("pipeline falhou: %s", exc)
        return 1
    print(report(result, failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
