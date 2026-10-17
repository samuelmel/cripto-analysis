"""Estratégias de referência avaliadas no motor único (`backtest_engine.py`), todas com as mesmas premissas.

Puro (CLAUDE.md §1). Substitui `trade_simulator.performance_summary` (motor `run_portfolio`) e
`trade_simulator.backtest` (operações com entrada no fechamento do dia do sinal) para os resultados publicados.

Sinais (decididos no fechamento de D, sem olhar para frente):
    TENDENCIA          `trade_simulator.trend_positions`: moeda e BTC acima da SMA 200, com o STOP de `ExitRules`
                       medido sobre o fechamento do primeiro dia do episódio (o stop é um sinal de fechamento)
    COMPRAR_E_SEGURAR  todas as moedas do universo com SMA 200
    PANICO             a regra antiga, congelada (`panic_backtest`), só como referência
Pesos: peso igual 1/N entre as moedas do universo que, em D, têm SMA 200 e são elegíveis (`eligible`, universo
point-in-time); cada estratégia fica comprada só nas moedas em que o sinal está ligado. A mesma banda de
rebalanceamento (`config.REBALANCE_BAND`), os mesmos custos e a mesma execução valem para todas, inclusive a
referência de comprar e segurar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest_engine import (
    SIDE_BUY,
    SIDE_SELL,
    SIDE_WRITE_OFF,
    BacktestResult,
    ExecutionConfig,
    MarketPanel,
    reconcile,
    run_backtest,
    summarize,
)
from .panic_backtest import panic_trades
from .trade_simulator import (
    EXIT_REGIME,
    EXIT_STOP,
    EXIT_TREND,
    PERFORMANCE_SCHEMA,
    STATUS_CLOSED,
    STATUS_OPEN,
    STOP_TOLERANCE,
    STRATEGY_HOLD,
    STRATEGY_PANIC,
    STRATEGY_TREND,
    TRADE_SCHEMA,
    ExitRules,
    positions_from_trades,
    trend_positions,
    wide,
)

EXIT_DELISTED = "DESLISTAGEM"  # baixa por falta de negociação (não acontece com BTC/ETH na base atual)


class ReconciliationError(ValueError):
    """O motor produziu livros que não fecham: nenhum resultado é publicado."""


def select_panel(panel: MarketPanel, symbols: list[str]) -> MarketPanel:
    cols = [s for s in symbols if s in panel.close.columns]
    return MarketPanel(panel.open[cols], panel.close[cols], panel.half_spread[cols])


def checked(result: BacktestResult, label: str) -> BacktestResult:
    problems = reconcile(result)
    if problems:
        raise ReconciliationError(f"{label}: " + "; ".join(problems))
    return result


def equal_weight(signal: pd.DataFrame, investable: pd.DataFrame) -> pd.DataFrame:
    """Peso 1/N em cada moeda com sinal ligado, N = moedas investíveis no dia (sinal desligado = caixa)."""
    ok = investable.reindex_like(signal).fillna(False).astype(bool)
    n = ok.sum(axis=1).replace(0, np.nan)
    return signal.astype(float).where(ok, 0.0).div(n, axis=0).fillna(0.0)


def strategy_signals(history: pd.DataFrame, rules: ExitRules = ExitRules()) -> dict[str, pd.DataFrame]:
    """Posição 0/1 por moeda e dia (decidida no fechamento) de cada estratégia de referência."""
    closes = wide(history, "close")
    return {
        STRATEGY_TREND: trend_positions(history, rules).reindex_like(closes).fillna(0.0),
        STRATEGY_HOLD: pd.DataFrame(1.0, index=closes.index, columns=closes.columns),
        STRATEGY_PANIC: positions_from_trades(panic_trades(history), pd.DatetimeIndex(closes.index), closes.columns),
    }


def investable_mask(history: pd.DataFrame, eligible: pd.DataFrame | None) -> pd.DataFrame:
    """Moeda investível em D: tem SMA 200 (todas as estratégias começam juntas) e, se informado, é elegível no
    universo point-in-time de D."""
    has_sma = wide(history, "sma_200").notna()
    if eligible is None:
        return has_sma
    return has_sma & eligible.reindex_like(has_sma).fillna(False).astype(bool)


def performance_summary(
    history: pd.DataFrame,
    panel: MarketPanel,
    universes: Mapping[str, tuple[str, ...]],
    periods: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]],
    cfg: ExecutionConfig,
    *,
    eligible: pd.DataFrame | None = None,
    rules: ExitRules = ExitRules(),
) -> pd.DataFrame:
    """Tendência x comprar e segurar x pânico por universo e período, no motor único (PERFORMANCE_SCHEMA)."""
    signals = strategy_signals(history, rules)
    investable = investable_mask(history, eligible)
    rows: list[dict[str, object]] = []
    for universe, symbols in universes.items():
        cols = [s for s in symbols if s in investable.columns and s in panel.close.columns]
        sub = select_panel(panel, cols)
        for strategy, signal in signals.items():
            targets = equal_weight(signal[cols], investable[cols])
            for period, (start, end) in periods.items():
                result = checked(run_backtest(sub, targets, eligible=investable[cols], cfg=cfg, start=start, end=end),
                                 f"{universe}/{strategy}/{period}")
                m = summarize(result)
                rows.append({
                    "universe": universe, "strategy": strategy, "period": period, "start": m["start"], "end": m["end"],
                    "total_return_pct": m["total"], "annual_return_pct": m["annual"], "max_drawdown_pct": m["drawdown"],
                    "sharpe": m["sharpe"], "invested_pct": m["invested"],
                })
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in PERFORMANCE_SCHEMA.items()})
    return pd.DataFrame(rows)[list(PERFORMANCE_SCHEMA)].astype(PERFORMANCE_SCHEMA)


def _exit_reason(history: pd.DataFrame, symbol: str, decided: pd.Timestamp, entry_close: float, rules: ExitRules) -> str:
    """Qual regra desligou a posição no fechamento `decided` (a mesma ordem de prioridade de `simulate`)."""
    row = history[(history["symbol"] == symbol) & (history["timestamp"] == decided)]
    if row.empty:
        return EXIT_TREND
    r = row.iloc[0]
    if rules.stop_loss is not None and float(r["close"]) / entry_close - 1.0 <= rules.stop_loss + STOP_TOLERANCE:
        return EXIT_STOP
    if pd.notna(r["sma_200"]) and float(r["close"]) < float(r["sma_200"]):
        return EXIT_TREND
    return EXIT_REGIME if not bool(r["regime_up"]) else EXIT_TREND


@dataclass(frozen=True)
class Fill:
    """Uma linha do livro de operações do motor, tipada."""

    side: str
    decided_at: pd.Timestamp | None
    executed_at: pd.Timestamp
    price: float
    notional: float
    fee: float


def fills(trades: pd.DataFrame) -> list[Fill]:
    out: list[Fill] = []
    for side, decided, executed, price, notional, fee in zip(
        trades["side"].astype(str), trades["decided_at"], trades["executed_at"], trades["execution_price"],
        trades["notional"], trades["fee"], strict=True,
    ):
        out.append(Fill(side, None if pd.isna(decided) else pd.Timestamp(decided), pd.Timestamp(executed),
                        float(price), float(notional), float(fee)))
    return out


def trend_trades(
    history: pd.DataFrame,
    panel: MarketPanel,
    symbols: tuple[str, ...],
    cfg: ExecutionConfig,
    *,
    eligible: pd.DataFrame | None = None,
    rules: ExitRules = ExitRules(),
) -> pd.DataFrame:
    """Cada operação da regra de tendência (TRADE_SCHEMA), com entrada e saída na abertura do dia seguinte ao sinal.

    Cada moeda é simulada sozinha (100% quando o sinal liga) no motor único; `entry_price`/`exit_price` são os
    preços EXECUTADOS (com meio-spread e slippage) e `return_pct` é líquido de taxa, spread e slippage de ida e volta.
    Operação ainda aberta: `return_pct` marcado no último fechamento, líquido só do custo de entrada.
    """
    positions = trend_positions(history, rules)
    investable = investable_mask(history, eligible)
    latest = history.sort_values("timestamp").groupby("symbol", observed=True).tail(1).set_index("symbol")
    closes_by_day = history.set_index(["symbol", "timestamp"])["close"]
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        if symbol not in positions.columns or symbol not in panel.close.columns:
            continue
        sub = select_panel(panel, [symbol])
        targets = positions[[symbol]].where(investable[[symbol]], 0.0).fillna(0.0)
        result = checked(run_backtest(sub, targets, cfg=cfg), f"operações {symbol}")
        closes = sub.close[symbol]
        entry: Fill | None = None
        for f in fills(result.trades):
            if f.side == SIDE_BUY and entry is None:
                entry = f
            elif f.side in (SIDE_SELL, SIDE_WRITE_OFF) and entry is not None:
                cost_in = entry.notional + entry.fee
                path = closes.loc[entry.executed_at:f.executed_at].dropna() / entry.price - 1.0
                if f.side == SIDE_WRITE_OFF or f.decided_at is None or entry.decided_at is None:
                    reason = EXIT_DELISTED
                else:
                    entry_close = float(closes_by_day.loc[(symbol, entry.decided_at)])
                    reason = _exit_reason(history, symbol, f.decided_at, entry_close, rules)
                rows.append(_trade_row(symbol, entry, latest, STATUS_CLOSED, f.executed_at, f.price, reason,
                                       (f.notional - f.fee) / cost_in - 1.0, path))
                entry = None
        if entry is not None:
            units = float(result.units[symbol].to_numpy()[-1])
            mark = float(closes.dropna().to_numpy()[-1])
            path = closes.loc[entry.executed_at:].dropna() / entry.price - 1.0
            rows.append(_trade_row(symbol, entry, latest, STATUS_OPEN, None, None, None,
                                   units * mark / (entry.notional + entry.fee) - 1.0, path))
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in TRADE_SCHEMA.items()})
    out = pd.DataFrame(rows)[list(TRADE_SCHEMA)]
    for col in ("entry_ts", "exit_ts", "last_ts"):
        out[col] = pd.to_datetime(out[col], utc=True)  # só operações abertas: exit_ts só com NaT, sem fuso
    return out.astype(TRADE_SCHEMA).sort_values(["symbol", "entry_ts"], ignore_index=True)


def _trade_row(
    symbol: str,
    buy: Fill,
    latest: pd.DataFrame,
    status: str,
    exit_ts: pd.Timestamp | None,
    exit_price: float | None,
    reason: str | None,
    net_return: float,
    path: pd.Series,
) -> dict[str, object]:
    last_ts = pd.Timestamp(latest["timestamp"].to_dict()[symbol])
    end = exit_ts if exit_ts is not None else last_ts
    return {
        "trade_id": f"{symbol}@{buy.executed_at:%Y-%m-%d}",
        "symbol": symbol,
        "entry_ts": buy.executed_at,
        "entry_price": buy.price,
        "status": status,
        "exit_ts": exit_ts if exit_ts is not None else pd.NaT,
        "exit_price": exit_price if exit_price is not None else np.nan,
        "exit_reason": reason if reason is not None else pd.NA,
        "return_pct": net_return * 100.0,
        "max_return_pct": float(path.max()) * 100.0 if not path.empty else np.nan,
        "min_return_pct": float(path.min()) * 100.0 if not path.empty else np.nan,
        "days_held": int((end - buy.executed_at).days),
        "last_ts": last_ts,
        "last_close": latest.loc[symbol, "close"],
        "sma_200": latest.loc[symbol, "sma_200"],
    }
