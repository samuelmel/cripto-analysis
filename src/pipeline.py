"""Pipeline diário: atualiza a base histórica -> analisa -> compara com ontem -> publica.

Uso (da raiz do projeto):
    uv run python -m src.pipeline              atualiza a base (incremental) e analisa
    uv run python -m src.pipeline --offline    só reanalisa a base local (sem internet)
    uv run python -m src.pipeline --rebuild    baixa todo o histórico de novo desde 2017

Base local (data/market/): candles diários desde a listagem de cada par na Binance e o
Fear & Greed completo (desde 2018). A primeira execução faz o download completo.

Publica em frontend/public/:
    daily_signals.parquet   snapshot do dia: estágio SMA 200, alertas, score, classificação e aporte de cada moeda
    recommendation.parquet  resumo da recomendação: orçamento, mercado, total sugerido, saldo, evidência, dados
    selection_backtest.parquet  a seleção contra referências simples, com custos, em treino, validação e teste
    market_regimes.parquet  regime de mercado do BTC por dia (tendência e volatilidade, causal); só descrição
    history.parquet         histórico de preço, indicadores e estágio (gráficos)
    backtest.parquet        cada operação histórica da regra de tendência (BTC e ETH), na abertura seguinte, líquida
    performance.parquet     carteira: tendência x comprar e segurar x pânico, em treino e teste
Os três backtests (selection_backtest, backtest, performance) usam o motor único (`backtest_engine.py`, premissas
`config.EXECUTION_MODEL_VERSION`) e o universo point-in-time; os livros são reconciliados antes de publicar.
    forecast.parquet        previsão de 1, 7 e 30 dias de BTC e ETH (faixa P10–P90) contra o baseline
    sources.parquet         quando e como cada fonte foi atualizada (alerta de falha de coleta)
    positions.parquet       suas posições com a recomendação VENDER / SEGURAR
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import (
    BUDGET_BRL,
    FORECAST_SEED,
    REBALANCE_BAND,
    RECOMMENDED,
    REGIME_FILTER,
    REGIME_SYMBOL,
    SELECTION_REBALANCE_DAYS,
    TEST_PERIOD,
    TRAIN_PERIOD,
    UNIVERSE,
    VALIDATION_BOOTSTRAP,
    VALIDATION_PERIOD,
    VALIDATION_SEED,
)
from .extractors import MARKET_SYMBOL, BaseExtractor, BinanceAdapter, CoinGeckoMarketAdapter, ExtractorError, FearGreedAdapter
from .extractors.binance_adapter import DEFAULT_HOST as BINANCE_DEFAULT_HOST
from .notifiers import TelegramError, send_messages, settings_from_env
from .loaders.evidence_store import read_entry_levels, read_exit_rules, read_signal_evidence
from .loaders.history_store import read_previous, write_snapshot
from .loaders.market_store import (
    MixedSourceError,
    append_dataset_manifest,
    last_timestamp,
    read_coingecko,
    read_fng,
    read_ohlcv,
    write_coingecko,
    write_fng,
    write_ohlcv,
)
from .loaders.parquet_loader import write_daily_signals, write_parquet
from .loaders.position_log_store import append_notifications, append_state_log, read_notifications, read_state_log
from .loaders.positions_store import read_positions
from .loaders.signal_log_store import append_signal_log
from .loaders.source_log import read_source_log, write_source_log
from .transformers.anomaly_detector import SignalRules, classify_history, detect
from .transformers.forecast import forecast_table
from .transformers.allocation import allocate
from .transformers.notification import (
    data_notes,
    format_entry_changes,
    format_error,
    format_position_changes,
    format_report,
    redact,
    validate_messages,
)
from .transformers.recommendation import build_recommendation, validate_recommendation
from .transformers.regimes import classify_market_regimes
from .transformers.selection import REGIME_UNAVAILABLE, assess, compute_features, features_on, regime_series
from .transformers.selection_backtest import evaluate_selection_runs, evidence_with_uncertainty
from .transformers.entry_live import (
    apply_entry_signals_to_stage,
    attach_entry_status,
    buy_mask,
    entry_changes,
    entry_status,
    live_conditions,
)
from .transformers.bootstrap import BootstrapConfig
from .transformers.strategies import market_from_candles
from .transformers.data_quality import audit_candles, availability, clean_candles, mark_unavailable
from .transformers.dataset import combined_fingerprint, dataset_manifest
from .transformers.daily_alerts import ALERT_BUY, ALERT_EXIT, ALERT_SELL, ALERT_WATCH, compare_with_previous
from .transformers.position_advisor import ACTION_SELL, ACTION_UNAVAILABLE, advise, realized
from .transformers.position_log import acknowledgements, new_state_rows, pending_changes
from .transformers.signal_registry import build_rows
from .transformers.universe import select_universe
from .transformers.backtest_engine import ExecutionConfig, MarketPanel, panel_from_candles
from .transformers.costs import CostModel
from .transformers.point_in_time import universe_history
from .transformers.portfolio_backtest import performance_summary, trend_trades
from .transformers.trade_simulator import (
    PERIOD_TEST,
    PERIOD_TRAIN,
    STRATEGY_HOLD,
    STRATEGY_TREND,
    wide,
)

logger = logging.getLogger("pipeline")

HISTORY_START = datetime(2017, 1, 1, tzinfo=timezone.utc)  # Binance spot começa em 2017
PUBLIC_DIR = Path("frontend/public")

VALIDATION = (pd.Timestamp(VALIDATION_PERIOD[0], tz="UTC"), pd.Timestamp(VALIDATION_PERIOD[1], tz="UTC"))
TEST = (pd.Timestamp(TEST_PERIOD[0], tz="UTC"), pd.Timestamp(TEST_PERIOD[1], tz="UTC"))
PERIODS: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
    PERIOD_TRAIN: (pd.Timestamp(TRAIN_PERIOD[0], tz="UTC"), pd.Timestamp(TRAIN_PERIOD[1], tz="UTC")),
    PERIOD_TEST: (pd.Timestamp(TEST_PERIOD[0], tz="UTC"), pd.Timestamp(TEST_PERIOD[1], tz="UTC")),
}
# Seleção: os mesmos três períodos do laboratório. Os pesos e limiares foram fixados antes (config.py); o teste
# só mede.
SELECTION_PERIODS: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
    "TREINO": (pd.Timestamp(TRAIN_PERIOD[0], tz="UTC"), VALIDATION[0] - pd.Timedelta(days=1)),
    "VALIDACAO": VALIDATION,
    "TESTE": TEST,
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


def update_base(now: datetime, *, rebuild: bool = False, binance_host: str = BINANCE_DEFAULT_HOST) -> pd.DataFrame:
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
            candles = BinanceAdapter([symbol], host=binance_host).extract(start, now)
            if not candles.empty:
                write_ohlcv(candles, ingested_at=pd.Timestamp(now))
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


def analyze(
    today: pd.Timestamp, *, budget: float = BUDGET_BRL, source_errors: pd.DataFrame | None = None, record_state: bool = False
) -> dict[str, pd.DataFrame]:
    """Análise completa sobre a base local. Não acessa a rede. `today` é a data e hora da análise (injetada);
    `budget` é o orçamento total da simulação; `source_errors` são as falhas de coleta desta execução. `record_state`: grava o
    registro de sinais e o histórico de estados em data/state (só o GitHub Actions faz isso, para o PC e o runner não
    divergirem); sem isso, o estado de hoje é calculado em memória e nada é gravado."""
    raw = read_ohlcv(list(UNIVERSE))
    if raw.empty:
        raise ExtractorError("base local vazia: rode sem --offline para baixar o histórico")

    selection = select_universe(UNIVERSE, raw)
    kept = raw[raw["symbol"].isin(selection.kept)]
    issues = audit_candles(kept, as_of=today)
    candles = clean_candles(kept)
    dataset = dataset_manifest(candles)  # identidade dos dados desta execução (linhas, intervalo, SHA-256 por moeda)
    fng = read_fng()

    # COMPRAR depende do sinal, não da moeda (docs/entry_signals.md): aparece quando a moeda está na condição de um
    # sinal VALIDADO no estudo agregado (evidence/entry_signals/). O COMPRAR/PREPARAR da regra SMA 200 é sempre rebaixado;
    # a evidência por moeda (evidence/signal_evidence.parquet) fica só como informação. Sem a tabela de níveis, nenhum sinal.
    signal_evidence = read_signal_evidence()
    entry_levels = read_entry_levels()
    entry_conds = live_conditions(candles, entry_levels)
    signal_rules = SignalRules(recommended=tuple(selection.kept))
    history = apply_entry_signals_to_stage(classify_history(candles, fng, signal_rules), buy_mask(entry_conds, entry_levels))
    available = availability(history, selection.kept, today)
    snapshot = mark_unavailable(detect(candles, read_coingecko(), fng, rules=signal_rules, history=history), available)
    day = pd.Timestamp(snapshot["timestamp"].max())
    # O dia anterior vem do próprio histórico recalculado: o alerta segue a regra atual mesmo que
    # os snapshots antigos em data/signals tenham sido gerados por uma regra diferente.
    previous = history[history["timestamp"].eq(day - pd.Timedelta(days=1))]
    signals = compare_with_previous(snapshot, previous if not previous.empty else read_previous(day))
    symbols = signals["symbol"].astype(str).tolist()
    signals = attach_entry_status(signals, entry_status(entry_conds, entry_levels, symbols, day))
    changes_today = entry_changes(entry_conds, entry_levels, symbols, day)

    # Seleção e aporte: calculados uma vez aqui; painel e Telegram só leem o resultado.
    features = compute_features(market_from_candles(candles))
    regimes = regime_series(features)
    unavailable = {str(r.symbol): str(r.reason) for r in available.itertuples() if not bool(r.available)}
    regime = REGIME_UNAVAILABLE if REGIME_SYMBOL in unavailable else str(regimes.get(day, REGIME_UNAVAILABLE))
    # Regimes de mercado (Fase 4): descrição causal publicada ao lado do regime antigo. Só leitura: não entra em
    # assess/allocate/evaluate_selection nem em nenhuma regra de compra, venda ou risco.
    ref = candles[candles["symbol"].eq(REGIME_SYMBOL)]
    market_regimes = classify_market_regimes(
        pd.Series(ref["close"].to_numpy(dtype="float64"), index=pd.DatetimeIndex(ref["timestamp"])),
        pd.Timestamp(today), legacy=regimes,
    )
    assessed = assess(features_on(features, day), regime, unavailable=unavailable)
    allocation, summary = allocate(assessed, budget, regime)
    # Backtests: motor único, mesmas premissas para todas as estratégias e referências, universo point-in-time.
    bt = backtest_inputs(raw, fng)
    selection_perf, _, selection_runs = evaluate_selection_runs(
        bt.features, regime_series(bt.features), SELECTION_PERIODS, budget, SELECTION_REBALANCE_DAYS, bt.panel, bt.cfg,
        eligible=bt.eligible,
    )
    signals, recommendation = build_recommendation(
        signals, assessed, allocation, summary,
        run_ts=pd.Timestamp(today), regime=regime, regime_filter=REGIME_FILTER, regime_symbol=REGIME_SYMBOL,
        excluded=[f"{s.split('/')[0]}: {why}" for s, why in selection.dropped.items()],
        evidence=evidence_with_uncertainty(selection_perf, selection_runs, "TESTE",
                                           BootstrapConfig(n_boot=VALIDATION_BOOTSTRAP, seed=VALIDATION_SEED)),
        data_notes=data_notes(available, source_errors),
    )
    problems = validate_recommendation(signals, recommendation)
    if problems:
        raise ValueError("recomendação inconsistente, nada publicado: " + "; ".join(problems))

    trades = trend_trades(bt.history, bt.panel, RECOMMENDED, bt.portfolio_cfg, eligible=bt.eligible)
    performance = performance_summary(
        bt.history, bt.panel, {"PRINCIPAIS": RECOMMENDED, "TODAS": bt.symbols}, PERIODS, bt.portfolio_cfg,
        eligible=bt.eligible,
    )
    positions = _publish_positions(history, available, read_exit_rules())
    # Só prevê moedas com dado confiável hoje; sem dado, não há previsão (nunca uma antiga apresentada como atual).
    usable = tuple(s for s in RECOMMENDED if s in set(available.loc[available["available"], "symbol"]))
    forecast = forecast_table(wide(history, "close"), usable, VALIDATION, TEST, FORECAST_SEED)

    write_snapshot(signals, day)
    append_dataset_manifest(dataset, pd.Timestamp(today))
    write_parquet(history, PUBLIC_DIR / "history.parquet")
    write_parquet(trades, PUBLIC_DIR / "backtest.parquet")
    write_parquet(performance, PUBLIC_DIR / "performance.parquet")
    write_parquet(forecast, PUBLIC_DIR / "forecast.parquet")
    write_parquet(selection_perf, PUBLIC_DIR / "selection_backtest.parquet")
    write_parquet(market_regimes, PUBLIC_DIR / "market_regimes.parquet")
    write_parquet(read_source_log(), PUBLIC_DIR / "sources.parquet")
    write_parquet(recommendation, PUBLIC_DIR / "recommendation.parquet")
    if not signal_evidence.empty:
        write_parquet(signal_evidence, PUBLIC_DIR / "signal_evidence.parquet")
    if not entry_levels.empty:
        write_parquet(entry_levels, PUBLIC_DIR / "entry_signal_levels.parquet")
    # Estado persistente (branch `state`): registro imutável de sinais e histórico de estados das posições.
    state_log = read_state_log()
    today_rows = new_state_rows(positions, state_log, day)
    if record_state:
        append_signal_log(build_rows(signals, signal_evidence, run_ts=pd.Timestamp(today), code_version=_code_version()))
        append_state_log(today_rows)
        state_log = read_state_log()
    elif not today_rows.empty:
        state_log = pd.concat([state_log, today_rows], ignore_index=True) if not state_log.empty else today_rows
    changes = pending_changes(state_log, read_notifications())
    write_parquet(state_log, PUBLIC_DIR / "position_states.parquet")
    write_daily_signals(signals)  # por último: o estado final da execução (CLAUDE.md §3)
    dropped = pd.DataFrame({"symbol": list(selection.dropped), "reason": list(selection.dropped.values())})
    return {
        "signals": signals, "backtest": trades, "performance": performance, "positions": positions, "forecast": forecast,
        "availability": available, "issues": issues, "dropped": dropped, "recommendation": recommendation,
        "selection_backtest": selection_perf, "market_regimes": market_regimes, "dataset": dataset,
        "position_changes": changes, "entry_levels": entry_levels, "entry_changes": changes_today,
        "signal_evidence": signal_evidence,
    }


@dataclass(frozen=True)
class BacktestInputs:
    history: pd.DataFrame      # indicadores de TODAS as moedas da base (não só as que passam no filtro de hoje)
    features: pd.DataFrame
    panel: MarketPanel
    eligible: pd.DataFrame     # universo point-in-time: elegível em cada dia só com dados até aquele dia
    symbols: tuple[str, ...]
    cfg: ExecutionConfig            # seleção: rebalanceamento semanal com banda (config.REBALANCE_BAND)
    portfolio_cfg: ExecutionConfig  # carteira de peso igual: rebalanceamento diário exato, todo custo cobrado


def backtest_inputs(raw: pd.DataFrame, fng: pd.DataFrame) -> BacktestInputs:
    """Entradas dos backtests a partir da base inteira. O universo de cada dia vem de `point_in_time` (histórico e
    volume medidos até o dia), e não de `select_universe`, que decide com os dados de hoje. As candidatas continuam
    sendo as moedas de config.UNIVERSE presentes na base (viés de sobrevivência da lista, documentado)."""
    candles = clean_candles(raw)
    history = classify_history(candles, fng)
    pit = universe_history(candles)
    eligible = pit.pivot(index="timestamp", columns="symbol", values="eligible").fillna(False).astype(bool)
    model = CostModel()
    return BacktestInputs(
        history=history,
        features=compute_features(market_from_candles(candles)),
        panel=panel_from_candles(candles, model),
        eligible=eligible,
        symbols=tuple(sorted(candles["symbol"].astype(str).unique())),
        cfg=ExecutionConfig(costs=model, rebalance_band=REBALANCE_BAND),
        # Peso igual entre ~32 moedas (~3% cada): uma banda absoluta de 5 pontos transformaria "peso igual" em
        # "deixar as vencedoras crescerem". A estratégia é a mesma do legado (peso igual todo dia), agora pagando o
        # rebalanceamento que o legado fazia de graça.
        portfolio_cfg=ExecutionConfig(costs=model, rebalance_band=0.0),
    )



def _code_version() -> str:
    """Versão do código desta execução: o commit do GitHub Actions, ou "local"."""
    return os.environ.get("GITHUB_SHA", "local")[:12] or "local"


def _publish_positions(history: pd.DataFrame, available: pd.DataFrame, rule_table: pd.DataFrame | None = None) -> pd.DataFrame:
    stored = read_positions()
    positions = advise(stored[~stored["closed"]], history, available=available, rule_table=rule_table)
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
    return _publish_positions(history, availability(history, selection.kept, pd.Timestamp(now)), read_exit_rules())


def report(result: dict[str, pd.DataFrame], source_errors: pd.DataFrame | None = None) -> str:
    signals, trades, performance, positions = result["signals"], result["backtest"], result["performance"], result["positions"]
    day = pd.Timestamp(signals["timestamp"].max())
    lines = [f"Ciclo {day:%Y-%m-%d} · {len(signals)} ativos · F&G {signals['fng_value'].iloc[0]}"]
    if "dataset" in result and not result["dataset"].empty:
        data = result["dataset"]
        lines.append(f"  dados: {int(data['rows'].sum())} candles de {len(data)} moedas · SHA-256 {combined_fingerprint(data)[:16]}")
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
    rec = result["recommendation"].iloc[0]
    lines.append(
        f"  seleção: mercado {rec['regime']} · {int(rec['n_candidates'])} candidata(s) · aporte sugerido "
        f"R$ {rec['total_brl']:.2f} de R$ {rec['budget_brl']:.2f} (não alocado R$ {rec['unallocated_brl']:.2f})"
    )
    for _, c in signals[signals["selected"]].sort_values("candidate_rank").iterrows():
        lines.append(f"    {c['symbol']}: {c['opportunity']} · score {c['score']:.0f} · R$ {c['allocation_brl']:.2f}")
    lines.append(f"  {rec['evidence']}")
    model = result["forecast"][result["forecast"]["role"].eq("MODELO")]
    if not model.empty:
        lines.append(f"  previsão 1/7/30 dias: {int(model['beats_baseline'].sum())} de {len(model)} superam o baseline no teste")
    for _, p in positions.iterrows():
        if p["action"] == ACTION_UNAVAILABLE:
            tag = f"INDISPONÍVEL ({p['data_note']})"
        else:
            tag = f"VENDER ({p['reason']})" if p["action"] == ACTION_SELL else "SEGURAR"
        lines.append(f"  posição {p['symbol']}: {p['return_pct']:+.1f}% → {tag}")
    return "\n".join(lines)


SECRET_ENV = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "COINGECKO_API_KEY")


def _secrets() -> list[str]:
    return [v for name in SECRET_ENV if (v := os.environ.get(name, "").strip())]


def _notify(result: dict[str, pd.DataFrame], now: datetime, *, dry_run: bool, record_state: bool = False) -> int:
    """Resumo do dia no Telegram mais, só quando o estado de alguma posição mudou, o aviso das posições (ou, com dry_run, só
    gerado, validado e impresso). 0 = ok, 1 = mensagem inválida, 2 = sem credenciais ou envio falhou (o job deve ficar
    vermelho). A mudança só é marcada como avisada depois do envio: se falhar, é reenviada na próxima execução."""
    texts = format_report(result["signals"], result["recommendation"], now=pd.Timestamp(now), recommended=RECOMMENDED,
                          entry_levels=result.get("entry_levels"), signal_evidence=result.get("signal_evidence"))
    changes = result.get("position_changes", pd.DataFrame())
    texts += format_position_changes(changes, now=pd.Timestamp(now))
    texts += format_entry_changes(result.get("entry_changes"), result["signals"], now=pd.Timestamp(now))
    problems = validate_messages(texts, _secrets())
    if problems:
        logger.error("mensagem do Telegram inválida: %s", "; ".join(problems))
        return 1
    if dry_run:
        for i, text in enumerate(texts, start=1):
            print(f"--- mensagem {i}/{len(texts)} ({len(text)} caracteres) ---")
            print(text)
        print("--- dry-run: mensagem válida, nada foi enviado ---")
        return 0
    settings = settings_from_env(os.environ)
    if settings is None:
        logger.error("--notify exige as variáveis TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
        return 2
    try:
        send_messages(settings, texts)
    except TelegramError as exc:
        logger.error("notificação falhou: %s", exc)
        return 2
    if record_state:
        append_notifications(acknowledgements(changes, pd.Timestamp(now)))
    logger.info("resumo enviado ao Telegram (%d mensagem(ns))", len(texts))
    return 0


def _alert_failure(stage: str, exc: BaseException, now: datetime) -> None:
    """Alerta curto de erro no Telegram, se estiver configurado. Nunca levanta: o erro original é o que importa."""
    settings = settings_from_env(os.environ)
    if settings is None:
        return
    try:
        send_messages(settings, format_error(stage, f"{type(exc).__name__}: {exc}", now=pd.Timestamp(now), secrets=_secrets()))
    except TelegramError as sending:
        logger.error("alerta de erro não enviado: %s", sending)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline diário do crypto-analyzer")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="só reanalisa a base local")
    mode.add_argument("--rebuild", action="store_true", help="baixa todo o histórico de novo")
    parser.add_argument("--notify", action="store_true", help="envia o resumo pelo Telegram")
    parser.add_argument("--record-state", action="store_true", help="grava o registro de sinais e o histórico de estados em data/state (GitHub Actions)")
    parser.add_argument("--dry-run", action="store_true", help="gera e valida a mensagem do Telegram sem enviar")
    parser.add_argument(
        "--budget", type=float, default=BUDGET_BRL,
        help=f"orçamento total da simulação em reais (padrão {BUDGET_BRL:.0f}); informe o saldo que ainda resta",
    )
    args = parser.parse_args(argv)
    if not (args.budget >= 0 and args.budget < float("inf")):
        parser.error("--budget precisa ser um valor >= 0")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    now = datetime.now(timezone.utc)
    stage = "coleta"
    try:
        failures = pd.DataFrame()
        if not args.offline:
            log = update_base(now, rebuild=args.rebuild, binance_host=os.environ.get("BINANCE_API_HOST", "").strip() or BINANCE_DEFAULT_HOST)
            failures = log[log["status"].eq("erro")]
        stage = "análise"
        result = analyze(pd.Timestamp(now), budget=args.budget, source_errors=failures, record_state=args.record_state)
    except ExtractorError as exc:
        logger.error("pipeline falhou: %s", exc)
        if args.notify and not args.dry_run:
            _alert_failure(stage, exc, now)
        return 1
    except Exception as exc:  # erro inesperado: avisa no Telegram e deixa o traceback no log
        logger.exception("pipeline falhou de forma inesperada")
        if args.notify and not args.dry_run:
            _alert_failure(stage, exc, now)
        return 1
    print(report(result, failures))
    if args.notify or args.dry_run:
        return _notify(result, now, dry_run=args.dry_run, record_state=args.record_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
