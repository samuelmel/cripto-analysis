"""Motor de backtest de referência: caixa, quantidades, ordens simuladas, custos e contabilidade reconciliável.

Puro (CLAUDE.md §1). Substitui, para todo resultado novo, os dois motores antigos (`trade_simulator.run_portfolio`
e `selection_backtest.run_weighted`, mantidos só para reproduzir resultados antigos; ver "Legado" abaixo).

Contrato (premissas em `config.py`, versão `config.EXECUTION_MODEL_VERSION`):

    Sinal       `targets`: em cada dia de decisão D, o peso-alvo de cada ativo (fração do patrimônio, >= 0, soma
                <= 1). Calculado com dados até o FECHAMENTO de D. Ativo ausente da linha = alvo 0 (vender).
    Universo    `eligible` (opcional, mesmo formato): só ativos elegíveis em D podem ter alvo > 0; os demais têm o
                alvo zerado (a posição existente é vendida). Use `point_in_time.universe_history`.
    Execução    a ordem decidida em D é executada na ABERTURA do primeiro candle depois de D (normalmente D+1).
                Nunca ao fechamento de D, que é o preço que gerou o sinal. Sem preço válido de abertura (candle
                ausente), a ordem fica pendente por até `max_order_delay_days`; depois expira, sem execução.
                Uma decisão nova substitui as ordens pendentes.
    Custos      compra a abertura × (1 + meio-spread + slippage), venda a abertura × (1 − meio-spread −
                slippage), taxa sobre o notional executado, paga em caixa (`costs.CostModel`). O meio-spread de
                cada ativo vem do volume médio conhecido até o dia anterior à execução.
    Caixa       vendas antes das compras; compras limitadas ao caixa (escaladas na mesma proporção quando não
                cabem, registradas com `fill_ratio`); sem alavancagem, sem venda a descoberto, caixa sem rendimento.
                O peso-alvo inclui os custos: alvo de 100% gasta todo o patrimônio, taxa e spread incluídos.
    Banda       posição mantida (atual e alvo > 0) só é reajustada se |alvo − peso atual| > `rebalance_band`.
    Marcação    patrimônio no fechamento: caixa + quantidades × fechamento; sem candle no dia, vale o último
                fechamento conhecido (sem retorno inventado).
    Deslistagem ativo em carteira sem candle há mais de `delist_after_days` (fim de episódio, ver
                `point_in_time`) é baixado: recebe `delist_recovery` × último preço (padrão 0 = perda total) e a
                baixa entra no livro de operações.

Saídas: patrimônio, caixa, retornos e exposição diários; quantidades e valores por ativo; livro de operações
(cada compra, venda e baixa com preço de referência, preço executado, taxa, custo de spread e de slippage); livro
de ordens (decisão, execução, atraso, status). `reconcile` confere a contabilidade.

Limites deliberados: não simula stop intradiário (stops são sinais de fechamento, executados na abertura seguinte,
o que já inclui o risco de gap); não modela liquidez do livro (ordens pequenas, hipótese do projeto); a abertura de
D+1 é uma aproximação do preço alcançável, não uma garantia.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config
from .costs import CostModel, half_spread

SIDE_BUY = "COMPRA"
SIDE_SELL = "VENDA"
SIDE_WRITE_OFF = "BAIXA"

ORDER_FILLED = "EXECUTADA"
ORDER_PARTIAL = "PARCIAL"            # compra limitada pelo caixa (fill_ratio < 1)
ORDER_BAND = "DENTRO_DA_BANDA"       # alvo próximo do atual: nada a fazer
ORDER_EXPIRED = "EXPIRADA"           # sem preço válido dentro do prazo
ORDER_SUPERSEDED = "SUBSTITUIDA"     # uma decisão nova chegou antes da execução
ORDER_DELISTED = "CANCELADA_BAIXA"   # o ativo parou de negociar com a ordem pendente
ORDER_NOT_ELIGIBLE = "FORA_DO_UNIVERSO"  # alvo > 0 num ativo não elegível no dia da decisão: tratado como alvo 0

PARTIAL_THRESHOLD = 0.999  # abaixo disso a compra é marcada como PARCIAL (custos de centavos não contam)
EPS = 1e-12

TRADE_SCHEMA: dict[str, str] = {
    "decided_at": "datetime64[ns, UTC]",   # fechamento em que o sinal foi calculado (NaT na baixa)
    "executed_at": "datetime64[ns, UTC]",  # candle cuja abertura executou a ordem (ou dia da baixa)
    "symbol": "string",
    "side": "string",                      # COMPRA / VENDA / BAIXA
    "quantity": "float64",
    "reference_price": "float64",          # abertura do candle de execução (último preço na baixa)
    "execution_price": "float64",          # com meio-spread e slippage
    "notional": "float64",                 # quantidade × preço executado
    "fee": "float64",
    "spread_cost": "float64",
    "slippage_cost": "float64",
    "cash_after": "float64",
}

ORDER_SCHEMA: dict[str, str] = {
    "decided_at": "datetime64[ns, UTC]",
    "symbol": "string",
    "target_weight": "float64",            # depois do filtro de universo
    "status": "string",
    "executed_at": "datetime64[ns, UTC]",
    "delay_days": "Int64",                 # dias entre o primeiro candle possível e a execução
    "fill_ratio": "float64",               # fração da compra desejada que coube no caixa (1 nas vendas)
}


@dataclass(frozen=True)
class ExecutionConfig:
    costs: CostModel = field(default_factory=CostModel)
    initial_capital: float = 1.0
    rebalance_band: float = 0.0
    max_order_delay_days: int = config.MAX_ORDER_DELAY_DAYS
    delist_after_days: int = config.EPISODE_GAP_DAYS
    delist_recovery: float = config.DELIST_RECOVERY
    min_trade_fraction: float = 1e-9      # operação menor que isso (fração do patrimônio) é ignorada
    version: str = config.EXECUTION_MODEL_VERSION

    def __post_init__(self) -> None:
        if not (self.initial_capital > 0 and math.isfinite(self.initial_capital)):
            raise ValueError("initial_capital precisa ser > 0")
        if not 0 <= self.rebalance_band < 1 or not 0 <= self.delist_recovery <= 1:
            raise ValueError("rebalance_band em [0, 1) e delist_recovery em [0, 1]")
        if self.max_order_delay_days < 0 or self.delist_after_days < 1:
            raise ValueError("max_order_delay_days >= 0 e delist_after_days >= 1")


@dataclass(frozen=True)
class MarketPanel:
    """Preços diários em formato largo (índice = todos os dias do calendário, colunas = ativos)."""

    open: pd.DataFrame
    close: pd.DataFrame
    half_spread: pd.DataFrame  # meio-spread estimado para executar no dia (só com volume até o dia anterior)


def _valid_price(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.where(np.isfinite(frame.to_numpy(dtype="float64")) & frame.gt(0))


def panel_from_candles(
    candles: pd.DataFrame, model: CostModel = CostModel(), volume_window: int = config.VOLUME_WINDOW_DAYS
) -> MarketPanel:
    """Candles padronizados (symbol, timestamp, open, close, quote_volume) -> MarketPanel. Dia sem candle = NaN."""
    c = candles.assign(timestamp=candles["timestamp"].dt.floor("D")).drop_duplicates(["symbol", "timestamp"], keep="last")
    days = pd.date_range(c["timestamp"].min(), c["timestamp"].max(), freq="D")

    def wide(col: str) -> pd.DataFrame:
        return c.pivot(index="timestamp", columns="symbol", values=col).reindex(days).astype("float64")

    volume = wide("quote_volume")
    avg = volume.rolling(volume_window, min_periods=max(1, volume_window * 2 // 3)).mean().shift(1)
    return MarketPanel(_valid_price(wide("open")), _valid_price(wide("close")), half_spread(avg, model))


@dataclass(frozen=True)
class BacktestResult:
    equity: pd.Series        # patrimônio no fechamento de cada dia
    cash: pd.Series
    returns: pd.Series       # retorno diário do patrimônio, líquido de todos os custos
    exposure: pd.Series      # valor em ativos / patrimônio, no fechamento
    units: pd.DataFrame      # quantidades no fechamento
    values: pd.DataFrame     # valor de cada posição no fechamento (marcação)
    trades: pd.DataFrame     # TRADE_SCHEMA
    orders: pd.DataFrame     # ORDER_SCHEMA
    config: ExecutionConfig


def _frame(rows: list[dict[str, object]], schema: dict[str, str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})
    out = pd.DataFrame(rows)[list(schema)]
    for col, dtype in schema.items():
        if dtype.startswith("datetime64"):
            out[col] = pd.to_datetime(out[col], utc=True)  # coluna só com NaT viria sem fuso
    return out.astype(schema)


def _clean_targets(targets: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if targets.empty:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC"), dtype="float64")
    t = targets.reindex(columns=cols).astype("float64").fillna(0.0).sort_index()
    values = t.to_numpy()
    if not np.isfinite(values).all() or (values < -EPS).any():
        raise ValueError("pesos-alvo precisam ser finitos e >= 0 (sem venda a descoberto)")
    if (values.sum(axis=1) > 1.0 + 1e-9).any():
        raise ValueError("soma dos pesos-alvo acima de 1 (sem alavancagem)")
    return t.clip(lower=0.0)


def run_backtest(
    panel: MarketPanel,
    targets: pd.DataFrame,
    *,
    eligible: pd.DataFrame | None = None,
    cfg: ExecutionConfig = ExecutionConfig(),
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> BacktestResult:
    """Simula `targets` sobre `panel` em [start, end] (inclusive), começando só em caixa."""
    cols = list(panel.close.columns)
    days = panel.close.loc[start:end].index
    n = len(cols)
    empty = pd.Series(dtype="float64")
    if len(days) == 0:
        return BacktestResult(empty, empty, empty, empty, pd.DataFrame(columns=cols), pd.DataFrame(columns=cols),
                              _frame([], TRADE_SCHEMA), _frame([], ORDER_SCHEMA), cfg)

    plan = _clean_targets(targets, cols)
    requested = plan.copy()
    if eligible is not None:
        ok = eligible.reindex(index=plan.index, columns=cols).fillna(False).astype(bool)
        plan = plan.where(ok, 0.0)
    plan_rows = {pd.Timestamp(d): i for i, d in enumerate(plan.index)}
    plan_values, requested_values = plan.to_numpy(), requested.to_numpy()

    opens = panel.open.reindex(index=days, columns=cols).to_numpy(dtype="float64")
    closes = panel.close.reindex(index=days, columns=cols).to_numpy(dtype="float64")
    spreads = panel.half_spread.reindex(index=days, columns=cols).ffill().to_numpy(dtype="float64")
    spreads = np.where(np.isfinite(spreads), spreads, cfg.costs.worst_half_spread)
    fee, slip = cfg.costs.fee_rate, cfg.costs.slippage

    # Último fechamento conhecido ANTES da janela (para marcar posições e medir dias sem candle desde o início).
    before = panel.close.reindex(columns=cols).loc[: days[0] - pd.Timedelta(days=1)]
    last_mark = before.ffill().iloc[-1].to_numpy(dtype="float64") if len(before) else np.full(n, np.nan)
    last_seen = np.full(n, -10**9, dtype=np.int64)
    if len(before):
        seen_before = before.notna().to_numpy()
        for j in range(n):
            idx = np.flatnonzero(seen_before[:, j])
            if idx.size:
                last_seen[j] = idx[-1] - len(before)  # índice relativo ao primeiro dia da janela

    cash = cfg.initial_capital
    units = np.zeros(n)
    pend_w = np.full(n, np.nan)           # alvo pendente (NaN = sem ordem)
    pend_decided = np.full(n, -1, dtype=np.int64)
    pend_from = np.full(n, -1, dtype=np.int64)  # primeiro dia em que a ordem podia ser executada
    trades: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    out_equity = np.zeros(len(days))
    out_cash = np.zeros(len(days))
    out_units = np.zeros((len(days), n))
    out_values = np.zeros((len(days), n))

    def day_ts(i: int) -> pd.Timestamp:
        return pd.Timestamp(days[i]) if i >= 0 else pd.Timestamp(days[0]) + pd.Timedelta(days=int(i))

    def close_order(j: int, status: str, executed: int | None, fill: float) -> None:
        orders.append({
            "decided_at": decided_ts[j], "symbol": cols[j], "target_weight": float(pend_w[j]), "status": status,
            "executed_at": day_ts(executed) if executed is not None else pd.NaT,
            "delay_days": (executed - pend_from[j]) if executed is not None else pd.NA, "fill_ratio": fill,
        })
        pend_w[j] = np.nan

    decided_ts: list[pd.Timestamp | None] = [None] * n

    def load_decision(row: int, decided: pd.Timestamp, first_exec: int) -> None:
        target = plan_values[row]
        for j in range(n):
            if not math.isnan(pend_w[j]):
                close_order(j, ORDER_SUPERSEDED, None, 0.0)
            if requested_values[row, j] > EPS and target[j] <= EPS:
                orders.append({"decided_at": decided, "symbol": cols[j], "target_weight": float(requested_values[row, j]),
                               "status": ORDER_NOT_ELIGIBLE, "executed_at": pd.NaT, "delay_days": pd.NA, "fill_ratio": 0.0})
            if target[j] > EPS or units[j] > EPS:
                pend_w[j] = target[j]
                pend_decided[j] = row
                pend_from[j] = first_exec
                decided_ts[j] = decided

    # Decisão mais recente ANTES da janela: conhecida no início, executada na primeira abertura da janela.
    prior = plan.index[plan.index < days[0]]
    if len(prior):
        load_decision(plan_rows[pd.Timestamp(prior[-1])], pd.Timestamp(prior[-1]), 0)

    for i in range(len(days)):
        o, cl, hs = opens[i], closes[i], spreads[i]
        tradable = np.isfinite(o)
        # ---- abertura: executa as ordens pendentes que têm preço -------------------------------------------
        marks_open = np.where(tradable, o, last_mark)
        held_value = np.where(units > EPS, units * np.nan_to_num(marks_open), 0.0)
        equity_open = cash + float(held_value.sum())
        has_order = ~np.isnan(pend_w)
        for j in map(int, np.flatnonzero(has_order & ~tradable)):
            if i - pend_from[j] > cfg.max_order_delay_days:
                close_order(j, ORDER_EXPIRED, None, 0.0)
        go = [int(j) for j in np.flatnonzero(has_order & tradable)]
        sells: list[tuple[int, float]] = []
        buys: list[tuple[int, float]] = []
        for j in go:
            target_w = float(pend_w[j])
            current_w = held_value[j] / equity_open if equity_open > EPS else 0.0
            if current_w > EPS and target_w > EPS and abs(target_w - current_w) <= cfg.rebalance_band:
                close_order(j, ORDER_BAND, i, 1.0)
                continue
            delta_value = (target_w - current_w) * equity_open
            if abs(delta_value) <= cfg.min_trade_fraction * max(equity_open, EPS):
                close_order(j, ORDER_BAND, i, 1.0)
            elif delta_value < 0:
                sells.append((j, min(units[j], -delta_value / o[j]) if target_w > EPS else units[j]))
            else:
                buys.append((j, delta_value))
        for j, qty in sells:
            price = o[j] * (1.0 - hs[j] - slip)
            gross = qty * price
            paid = gross * fee
            cash += gross - paid
            units[j] -= qty
            if units[j] < EPS:
                units[j] = 0.0
            trades.append({"decided_at": decided_ts[j], "executed_at": day_ts(i), "symbol": cols[j], "side": SIDE_SELL,
                           "quantity": qty, "reference_price": o[j], "execution_price": price, "notional": gross,
                           "fee": paid, "spread_cost": qty * o[j] * hs[j], "slippage_cost": qty * o[j] * slip,
                           "cash_after": cash})
            close_order(j, ORDER_FILLED, i, 1.0)
        wanted = sum(v for _, v in buys)
        scale = min(1.0, cash / wanted) if wanted > EPS else 1.0
        for j, value in buys:
            spend = value * scale
            if spend <= cfg.min_trade_fraction * max(equity_open, EPS):
                close_order(j, ORDER_PARTIAL, i, 0.0)  # sem caixa para comprar: nada é executado
                continue
            price = o[j] * (1.0 + hs[j] + slip)
            qty = spend / (price * (1.0 + fee))
            paid = qty * price * fee
            cash -= qty * price + paid
            if cash < 0 and cash > -1e-9 * cfg.initial_capital:
                cash = 0.0  # arredondamento
            units[j] += qty
            trades.append({"decided_at": decided_ts[j], "executed_at": day_ts(i), "symbol": cols[j], "side": SIDE_BUY,
                           "quantity": qty, "reference_price": o[j], "execution_price": price, "notional": qty * price,
                           "fee": paid, "spread_cost": qty * o[j] * hs[j], "slippage_cost": qty * o[j] * slip,
                           "cash_after": cash})
            close_order(j, ORDER_PARTIAL if scale < PARTIAL_THRESHOLD else ORDER_FILLED, i, scale)

        # ---- fechamento: marcação, baixa de quem parou de negociar, nova decisão ---------------------------
        seen = np.isfinite(cl)
        last_mark = np.where(seen, cl, last_mark)
        last_seen = np.where(seen, i, last_seen)
        for j in map(int, np.flatnonzero((units > EPS) & (i - last_seen > cfg.delist_after_days))):
            recovered = units[j] * float(np.nan_to_num(last_mark[j])) * cfg.delist_recovery
            cash += recovered
            trades.append({"decided_at": pd.NaT, "executed_at": day_ts(i), "symbol": cols[j], "side": SIDE_WRITE_OFF,
                           "quantity": units[j], "reference_price": float(last_mark[j]),
                           "execution_price": float(last_mark[j]) * cfg.delist_recovery, "notional": recovered,
                           "fee": 0.0, "spread_cost": 0.0, "slippage_cost": 0.0, "cash_after": cash})
            units[j] = 0.0
            if not math.isnan(pend_w[j]):
                close_order(j, ORDER_DELISTED, None, 0.0)
        values = units * np.nan_to_num(last_mark)
        out_values[i] = values
        out_units[i] = units
        out_cash[i] = cash
        out_equity[i] = cash + float(values.sum())
        row = plan_rows.get(pd.Timestamp(days[i]))
        if row is not None and i < len(days) - 1:
            load_decision(row, pd.Timestamp(days[i]), i + 1)

    for j in map(int, np.flatnonzero(~np.isnan(pend_w))):  # ordens que a janela terminou antes de executar
        close_order(j, ORDER_EXPIRED, None, 0.0)

    index = pd.DatetimeIndex(days)
    equity = pd.Series(out_equity, index=index)
    previous = equity.shift(1).fillna(cfg.initial_capital)
    returns = equity / previous - 1.0
    exposure = pd.Series(out_values.sum(axis=1), index=index) / equity.where(equity > EPS)
    return BacktestResult(
        equity=equity,
        cash=pd.Series(out_cash, index=index),
        returns=returns,
        exposure=exposure.fillna(0.0),
        units=pd.DataFrame(out_units, index=index, columns=cols),
        values=pd.DataFrame(out_values, index=index, columns=cols),
        trades=_frame(trades, TRADE_SCHEMA),
        orders=_frame(orders, ORDER_SCHEMA),
        config=cfg,
    )


def reconcile(result: BacktestResult, tolerance: float = 1e-9) -> list[str]:
    """Confere a contabilidade do resultado. Lista vazia = consistente. Tolerância relativa ao capital inicial."""
    problems: list[str] = []
    if result.equity.empty:
        return problems
    cap = result.config.initial_capital
    tol = tolerance * cap
    t = result.trades
    flows = pd.Series(0.0, index=result.cash.index)
    if not t.empty:
        sign = np.select([t["side"].eq(SIDE_BUY), t["side"].eq(SIDE_SELL)], [-1.0, 1.0], 1.0)
        fee_sign = np.where(t["side"].eq(SIDE_WRITE_OFF), 0.0, -1.0)
        cash_delta = sign * t["notional"].to_numpy() + fee_sign * t["fee"].to_numpy()
        flows = pd.Series(cash_delta, index=t["executed_at"]).groupby(level=0).sum().reindex(result.cash.index, fill_value=0.0)
    expected_cash = cap + flows.cumsum()
    if (expected_cash - result.cash).abs().max() > tol:
        problems.append("caixa diferente do capital inicial mais os fluxos das operações")
    if (result.cash < -tol).any():
        problems.append("caixa negativo (alavancagem)")
    if (result.units < -tol).to_numpy().any():
        problems.append("quantidade negativa (venda a descoberto)")
    if (result.equity - (result.cash + result.values.sum(axis=1))).abs().max() > tol:
        problems.append("patrimônio diferente de caixa + valor das posições")
    growth = float(np.prod(1.0 + result.returns.to_numpy(dtype="float64")))
    if abs(growth * cap - float(result.equity.to_numpy()[-1])) > tol * max(1.0, growth):
        problems.append("retornos diários não reproduzem o patrimônio final")
    if (result.exposure > 1.0 + 1e-9).any():
        problems.append("exposição acima de 100% do patrimônio")
    if not t.empty:
        sold = t[t["side"].eq(SIDE_SELL)].groupby("symbol")["quantity"].sum()
        bought = t[t["side"].eq(SIDE_BUY)].groupby("symbol")["quantity"].sum()
        written = t[t["side"].eq(SIDE_WRITE_OFF)].groupby("symbol")["quantity"].sum()
        net = bought.sub(sold, fill_value=0.0).sub(written, fill_value=0.0)
        final = result.units.iloc[-1].reindex(net.index).fillna(0.0)
        if (net - final).abs().max() > 1e-9 * max(1.0, float(bought.max()) if not bought.empty else 1.0):
            problems.append("quantidade final diferente de compras − vendas − baixas")
    return problems


def total_costs(result: BacktestResult) -> dict[str, float]:
    """Custos pagos no período, em fração do capital inicial: taxa, spread, slippage e total."""
    t = result.trades
    cap = result.config.initial_capital
    fee = float(t["fee"].sum()) / cap
    spread = float(t["spread_cost"].sum()) / cap
    slip = float(t["slippage_cost"].sum()) / cap
    return {"fee": fee, "spread": spread, "slippage": slip, "total": fee + spread + slip}


def summarize(result: BacktestResult) -> dict[str, float | pd.Timestamp]:
    """Métricas descritivas do período (365 dias por ano, sem taxa livre de risco). Fase 3 trata incerteza e
    amostras pequenas; aqui só se descreve o que a simulação produziu."""
    r = result.returns
    nan = float("nan")
    if r.empty:
        return {"start": pd.Timestamp("NaT"), "end": pd.Timestamp("NaT"), "total": nan, "annual": nan, "drawdown": nan, "sharpe": nan,
                "invested": nan, "turnover_per_year": nan, "n_trades": 0.0, "cost_pct": nan}
    equity = result.equity / result.config.initial_capital
    years = len(r) / 365
    vol = float(r.std() * np.sqrt(365))
    t = result.trades
    traded = float(t.loc[t["side"].isin([SIDE_BUY, SIDE_SELL]), "notional"].sum())
    mean_equity = float(result.equity.mean())
    held = result.units.gt(EPS)
    entries = int((held & ~held.shift(1, fill_value=False)).to_numpy().sum())  # de zerado para comprado
    return {
        "start": pd.Timestamp(r.index[0]),
        "end": pd.Timestamp(r.index[-1]),
        "total": (float(equity.iloc[-1]) - 1.0) * 100.0,
        "annual": (float(equity.iloc[-1]) ** (1.0 / years) - 1.0) * 100.0 if float(equity.iloc[-1]) > 0 else -100.0,
        "drawdown": float((equity / equity.cummax() - 1.0).min()) * 100.0,
        "sharpe": float(r.mean() * 365) / vol if vol > 0 else nan,
        "invested": float(result.exposure.mean()) * 100.0,
        "turnover_per_year": traded / mean_equity / years if mean_equity > 0 else nan,
        "n_trades": float(entries),
        "cost_pct": total_costs(result)["total"] * 100.0,
    }
