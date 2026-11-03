"""Carteiras simuladas em reais (dinheiro fictício): decisões de cada robô, replay e resumo. Regras: docs/sim_wallets.md.

Puro (CLAUDE.md §1). Nenhuma ordem real é enviada e não há integração com corretora: o que existe é a contabilidade de
um caixa fictício de R$ 1.000,00 por carteira.

Carteiras:
    PAINEL     segue a recomendação diária (moedas `selected` com aporte) e vende a posição inteira quando
               `position_advisor.advise` (as regras de saída das posições reais) devolve VENDER
    IA         modelo G_GBM em sombra (G_GBM_SEM_FNG no dia sem Fear & Greed): todo dia as 5 de maior probabilidade
               com 1/30 do capital inicial; cada lote sai 30 dias depois
    REVERSAO   EXPERIMENTAL, SEM ESTUDO: só com o BTC acima da SMA 200, as 5 moedas do universo do dia com o pior
               retorno de 90 dias, com o lote da IA; cada lote sai 30 dias depois
    SO_BTC     compra R$ 1.000,00 de BTC no primeiro dia e segura (referência)

Registro e replay: o que se grava são só as DECISÕES (`DECISION_SCHEMA`, append-only, cadeia de hash como a de
`model_shadow`). Posições, caixa e valor são recalculados a cada execução por `replay` a partir das decisões e dos
preços, então qualquer pessoa reproduz o mesmo número.

Execução honesta (como `backtest_engine`): decisão no fechamento do dia D, execução na ABERTURA de D+1 (fica PENDENTE
até esse candle existir), compra a abertura × (1 + meio-spread + slippage), venda a abertura × (1 − meio-spread −
slippage), taxa sobre o notional (`costs.CostModel`). Sem alavancagem e sem caixa negativo: compra que não cabe no caixa
é NAO_EXECUTADA, com o motivo. Vendas antes das compras no mesmo dia. O valor em R$ de uma compra já inclui a taxa.

Moeda: preços em USDT, caixa em reais. Compra e venda convertem pela cotação USDT/BRL da abertura do dia da execução;
o valor do dia usa o fechamento. Sem cotação no dia, nada é inventado: a compra não é executada e o resumo sai em USDT.
O custo de converter reais em USDT não é simulado.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Hashable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import config
from .backtest_engine import SIDE_BUY, SIDE_SELL, panel_from_candles
from .costs import CostModel
from .entry_signals import Panel, trailing_return
from .model_shadow import GENESIS, _cell
from .position_advisor import ACTION_SELL, advise

PAINEL = "PAINEL"
IA = "IA"
REVERSAO = "REVERSAO"
SO_BTC = "SO_BTC"
WALLETS: tuple[str, ...] = (PAINEL, IA, REVERSAO, SO_BTC)
LABELS: dict[str, str] = {
    PAINEL: "Recomendação do painel",
    IA: "IA (boosting)",
    REVERSAO: "Reversão (experimental, sem estudo)",
    SO_BTC: "Só BTC (referência)",
}

STATUS_DONE = "EXECUTADA"
STATUS_PENDING = "PENDENTE"
STATUS_NOT_DONE = "NAO_EXECUTADA"
CURRENCY_BRL = "BRL"
CURRENCY_USDT = "USDT"
EPS = 1e-9


@dataclass(frozen=True)
class SimRules:
    initial_brl: float = 1000.0
    hold_days: int = 30
    top_k: int = 5
    reversal_days: int = 90
    ia_model: str = "G_GBM"
    ia_fallback: str = "G_GBM_SEM_FNG"
    btc_symbol: str = config.REGIME_SYMBOL

    @property
    def lot_brl(self) -> float:
        """Uma fatia por dia: 1/30 do capital inicial (dividida entre as moedas do dia)."""
        return self.initial_brl / self.hold_days


# ---------------------------------------------------------------------------------------------
# Registro de decisões (append-only, cadeia de hash)
# ---------------------------------------------------------------------------------------------

BARE_COLUMNS: tuple[str, ...] = ("wallet", "day", "symbol", "side", "lot_day", "amount_brl", "reason")
DECISION_SCHEMA: dict[str, str] = {
    "wallet": "string",
    "day": "datetime64[ns, UTC]",       # dia do fechamento que gerou a decisão (a execução é na abertura de day+1)
    "symbol": "string",
    "side": "string",                   # COMPRA ou VENDA
    "lot_day": "datetime64[ns, UTC]",   # dia do lote (compra: o próprio dia); nulo na venda da posição inteira
    "amount_brl": "float64",            # compra: R$ a gastar (taxa incluída); venda: valor estimado no fechamento
    "reason": "string",
    "run_ts": "datetime64[ns, UTC]",
    "code_version": "string",
    "prev_hash": "string",
    "row_hash": "string",
}
_PAYLOAD = tuple(c for c in DECISION_SCHEMA if c not in ("prev_hash", "row_hash"))
_KEY = ("wallet", "day", "symbol", "side")

Row = tuple[str, str, pd.Timestamp | None, float, str]
"""(moeda, lado, dia do lote, valor em R$, motivo)."""


def empty_log() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in DECISION_SCHEMA.items()})


def empty_bare() -> pd.DataFrame:
    return empty_log()[list(BARE_COLUMNS)]


def _bare(wallet: str, day: pd.Timestamp, rows: list[Row]) -> pd.DataFrame:
    if not rows:
        return empty_bare()
    frame = pd.DataFrame({
        "wallet": wallet, "day": day, "symbol": [r[0] for r in rows], "side": [r[1] for r in rows],
        "lot_day": pd.Series([pd.NaT if r[2] is None else r[2] for r in rows], dtype="datetime64[ns, UTC]"), "amount_brl": [r[3] for r in rows],
        "reason": [r[4] for r in rows],
    })
    return frame.astype({c: DECISION_SCHEMA[c] for c in BARE_COLUMNS})


def stamp(bare: pd.DataFrame, *, run_ts: pd.Timestamp, code_version: str) -> pd.DataFrame:
    """Decisões prontas para o registro (ainda sem a cadeia de hash)."""
    return bare.assign(run_ts=run_ts, code_version=code_version)


def row_hash(prev_hash: str, row: Mapping[Hashable, object]) -> str:
    payload = "|".join(_cell(row[c]) for c in _PAYLOAD)
    return hashlib.sha256(f"{prev_hash}|{payload}".encode("utf-8")).hexdigest()


def chain_rows(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Só as decisões novas (carteira, dia, moeda e lado ainda ausentes), encadeadas a partir do último hash."""
    seen = set(zip(*(existing[k] for k in _KEY), strict=True)) if not existing.empty else set()
    fresh = new[[key not in seen for key in zip(*(new[k] for k in _KEY), strict=True)]]
    fresh = fresh.sort_values(list(_KEY), ignore_index=True)
    prev = str(existing["row_hash"].iloc[-1]) if not existing.empty else GENESIS
    previous, hashes = [], []
    for row in fresh.to_dict("records"):
        previous.append(prev)
        prev = row_hash(prev, row)
        hashes.append(prev)
    return fresh.assign(prev_hash=previous, row_hash=hashes)[list(DECISION_SCHEMA)].astype(DECISION_SCHEMA)


def verify_chain(log: pd.DataFrame) -> list[str]:
    """Problemas da cadeia (vazia = íntegra)."""
    problems: list[str] = []
    prev = GENESIS
    for i, row in enumerate(log.to_dict("records")):
        if str(row["prev_hash"]) != prev:
            problems.append(f"linha {i}: elo quebrado")
        if row_hash(str(row["prev_hash"]), row) != str(row["row_hash"]):
            problems.append(f"linha {i}: conteúdo alterado")
        prev = str(row["row_hash"])
    if log.duplicated(list(_KEY)).any():
        problems.append("(carteira, dia, moeda, lado) repetido")
    return problems[:20]


def with_new(stored: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    """As decisões gravadas mais as de hoje ainda não gravadas (execução sem --record-state), sem repetir chave."""
    if fresh.empty:
        return stored
    base = stored[list(BARE_COLUMNS)]
    merged = pd.concat([base, fresh[list(BARE_COLUMNS)]], ignore_index=True) if not base.empty else fresh[list(BARE_COLUMNS)]
    return merged.drop_duplicates(list(_KEY), keep="first", ignore_index=True)


# ---------------------------------------------------------------------------------------------
# Mercado e replay
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SimMarket:
    """Preços diários (índice = calendário completo): abertura e fechamento em USDT, meio-spread do dia da execução
    (só com volume até o dia anterior) e cotação USDT/BRL (NaN = sem cotação no dia)."""

    open: pd.DataFrame
    close: pd.DataFrame
    half_spread: pd.DataFrame
    fx_open: pd.Series
    fx_close: pd.Series
    costs: CostModel = CostModel()


def sim_market(candles: pd.DataFrame, fx_candles: pd.DataFrame, costs: CostModel = CostModel()) -> SimMarket:
    panel = panel_from_candles(candles, costs)
    index = panel.close.index
    if fx_candles.empty:
        nan = pd.Series(np.nan, index=index, dtype="float64")
        return SimMarket(panel.open, panel.close, panel.half_spread, nan, nan.copy(), costs)
    fx = fx_candles.assign(timestamp=fx_candles["timestamp"].dt.floor("D")).drop_duplicates("timestamp", keep="last")
    fx = fx.set_index("timestamp").reindex(index)

    def rate(col: str) -> pd.Series:
        s = fx[col].astype("float64")
        return s.where(np.isfinite(s) & s.gt(0))

    return SimMarket(panel.open, panel.close, panel.half_spread, rate("open"), rate("close"), costs)


TRADE_SCHEMA: dict[str, str] = {
    "wallet": "string", "decision_day": "datetime64[ns, UTC]", "exec_day": "datetime64[ns, UTC]", "symbol": "string",
    "side": "string", "lot_day": "datetime64[ns, UTC]", "amount_brl": "float64", "status": "string", "reason": "string",
    "qty": "float64", "price_usdt": "float64", "fx": "float64", "fee_brl": "float64",
    "value_brl": "float64",    # compra: o que saiu do caixa; venda: o que entrou (taxa descontada)
    "cost_brl": "float64",     # venda: o que foi pago pelo que saiu
    "return_pct": "float64",   # venda: resultado sobre o custo
}
LOT_SCHEMA: dict[str, str] = {
    "wallet": "string", "symbol": "string", "lot_day": "datetime64[ns, UTC]", "exec_day": "datetime64[ns, UTC]",
    "qty": "float64", "cost_brl": "float64", "cost_usdt": "float64", "paid_usdt": "float64", "value_usdt": "float64",
    "value_brl": "float64", "sale_pending": "bool",
}
POSITION_SCHEMA: dict[str, str] = {
    "wallet": "string", "symbol": "string", "n_lots": "int64", "first_buy": "datetime64[ns, UTC]", "qty": "float64",
    "cost_brl": "float64", "cost_usdt": "float64", "avg_price_usdt": "float64", "last_close_usdt": "float64",
    "value_usdt": "float64", "value_brl": "float64", "return_pct": "float64", "pnl_brl": "float64",
}
SUMMARY_SCHEMA: dict[str, str] = {
    "wallet": "string", "label": "string", "start": "datetime64[ns, UTC]", "as_of": "datetime64[ns, UTC]",
    "initial_brl": "float64", "cash_brl": "float64", "positions_usdt": "float64", "positions_brl": "float64",
    "total_brl": "float64", "return_pct": "float64", "n_coins": "int64", "n_buys": "int64", "n_sells": "int64",
    "n_pending": "int64", "n_not_executed": "int64", "currency": "string", "fx_close": "float64",
}


def _empty(schema: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schema.items()})


@dataclass(frozen=True)
class SimState:
    trades: pd.DataFrame      # TRADE_SCHEMA: uma linha por decisão
    lots: pd.DataFrame        # LOT_SCHEMA: lotes abertos
    positions: pd.DataFrame   # POSITION_SCHEMA: lotes agrupados por moeda
    summary: pd.DataFrame     # SUMMARY_SCHEMA: uma linha por carteira


def empty_state() -> SimState:
    return SimState(_empty(TRADE_SCHEMA), _empty(LOT_SCHEMA), _empty(POSITION_SCHEMA), _empty(SUMMARY_SCHEMA))


@dataclass
class _Lot:
    exec_day: pd.Timestamp
    qty: float = 0.0
    cost_brl: float = 0.0
    cost_usdt: float = 0.0
    paid_usdt: float = 0.0


def _num(value: object) -> float:
    return float(value) if isinstance(value, int | float | np.integer | np.floating) else math.nan


def _ts(value: object) -> pd.Timestamp:
    if not isinstance(value, pd.Timestamp):
        raise TypeError(f"data esperada, veio {type(value).__name__}")
    return value


def _opt_ts(value: object) -> pd.Timestamp | None:
    return value if isinstance(value, pd.Timestamp) else None


def _price(frame: pd.DataFrame, day: pd.Timestamp, symbol: str) -> float:
    if day not in frame.index or symbol not in frame.columns:
        return math.nan
    return _num(frame.at[day, symbol])


def _rate(series: pd.Series, day: pd.Timestamp) -> float:
    return _num(series.at[day]) if day in series.index else math.nan


def _trade(d: Mapping[Hashable, object], exec_day: pd.Timestamp, status: str, reason: str = "") -> dict[str, object]:
    return {
        "wallet": str(d["wallet"]), "decision_day": _ts(d["day"]), "exec_day": exec_day, "symbol": str(d["symbol"]),
        "side": str(d["side"]), "lot_day": d["lot_day"], "amount_brl": _num(d["amount_brl"]), "status": status,
        "reason": reason, "qty": math.nan, "price_usdt": math.nan, "fx": math.nan, "fee_brl": math.nan, "value_brl": math.nan,
        "cost_brl": math.nan, "return_pct": math.nan,
    }


def replay(decisions: pd.DataFrame, market: SimMarket, rules: SimRules = SimRules()) -> SimState:
    """Refaz as carteiras do zero: aplica as decisões em ordem, na abertura do dia seguinte, e avalia no último fechamento.
    Determinístico: as mesmas decisões e os mesmos preços dão o mesmo resultado."""
    if market.close.empty or decisions.empty:
        return empty_state()
    as_of = pd.Timestamp(market.close.index.max())
    costs = market.costs
    cash = {w: rules.initial_brl for w in WALLETS}
    lots: dict[tuple[str, str, pd.Timestamp], _Lot] = {}
    trades: list[dict[str, object]] = []
    pending_sales: set[tuple[str, str, pd.Timestamp | None]] = set()

    ordered = decisions.assign(_buy=decisions["side"].eq(SIDE_BUY)).sort_values(["day", "wallet", "_buy", "symbol"])
    for d in ordered.to_dict("records"):
        wallet, symbol, side = str(d["wallet"]), str(d["symbol"]), str(d["side"])
        day = _ts(d["day"])
        exec_day = day + pd.Timedelta(days=1)
        lot_day = _opt_ts(d["lot_day"])
        row = _trade(d, exec_day, STATUS_DONE)
        if exec_day > as_of:
            row["status"] = STATUS_PENDING
            trades.append(row)
            if side == SIDE_SELL:
                pending_sales.add((wallet, symbol, lot_day))
            continue
        price, rate = _price(market.open, exec_day, symbol), _rate(market.fx_open, exec_day)
        half = _price(market.half_spread, exec_day, symbol)
        half = costs.worst_half_spread if not math.isfinite(half) else half
        if not math.isfinite(price):
            row.update(status=STATUS_NOT_DONE, reason=f"sem preço de abertura em {exec_day:%d/%m}")
        elif not math.isfinite(rate):
            row.update(status=STATUS_NOT_DONE, reason=f"cotação do real indisponível em {exec_day:%d/%m}")
        elif side == SIDE_BUY:
            amount = _num(d["amount_brl"])
            if amount > cash[wallet] + EPS:
                row.update(status=STATUS_NOT_DONE, reason="caixa insuficiente")
            else:
                notional = amount / (1.0 + costs.fee_rate)
                fill = price * (1.0 + half + costs.slippage)
                qty = notional / rate / fill
                cash[wallet] -= amount
                lot = lots.setdefault((wallet, symbol, day if lot_day is None else lot_day), _Lot(exec_day))
                lot.qty += qty
                lot.cost_brl += amount
                lot.cost_usdt += amount / rate
                lot.paid_usdt += qty * fill
                row.update(qty=qty, price_usdt=fill, fx=rate, fee_brl=amount - notional, value_brl=amount, cost_brl=amount)
        else:
            keys = [k for k in lots if k[0] == wallet and k[1] == symbol and (lot_day is None or k[2] == lot_day)]
            if not keys:
                row.update(status=STATUS_NOT_DONE, reason="sem posição para vender")
            else:
                qty = sum(lots[k].qty for k in keys)
                cost = sum(lots[k].cost_brl for k in keys)
                fill = price * (1.0 - half - costs.slippage)
                gross = qty * fill
                fee = gross * costs.fee_rate
                proceeds = (gross - fee) * rate
                cash[wallet] += proceeds
                for k in keys:
                    del lots[k]
                row.update(qty=qty, price_usdt=fill, fx=rate, fee_brl=fee * rate, value_brl=proceeds, cost_brl=cost,
                           return_pct=(proceeds / cost - 1.0) * 100.0)
        trades.append(row)
    return _state(trades, lots, cash, pending_sales, market, rules, decisions, as_of)


def _state(
    trades: list[dict[str, object]], lots: dict[tuple[str, str, pd.Timestamp], _Lot], cash: dict[str, float],
    pending_sales: set[tuple[str, str, pd.Timestamp | None]], market: SimMarket, rules: SimRules, decisions: pd.DataFrame,
    as_of: pd.Timestamp,
) -> SimState:
    last = market.close.ffill().iloc[-1]
    fx = _rate(market.fx_close, as_of)
    lot_rows: list[dict[str, object]] = []
    for (wallet, symbol, lot_day), lot in sorted(lots.items()):
        close = _num(last.get(symbol))
        value_usdt = lot.qty * close
        lot_rows.append({
            "wallet": wallet, "symbol": symbol, "lot_day": lot_day, "exec_day": lot.exec_day, "qty": lot.qty,
            "cost_brl": lot.cost_brl, "cost_usdt": lot.cost_usdt, "paid_usdt": lot.paid_usdt, "value_usdt": value_usdt,
            "value_brl": value_usdt * fx,
            "sale_pending": (wallet, symbol, lot_day) in pending_sales or (wallet, symbol, None) in pending_sales,
        })
    trade_frame = pd.DataFrame(trades, columns=list(TRADE_SCHEMA)).astype(TRADE_SCHEMA)
    lot_frame = pd.DataFrame(lot_rows, columns=list(LOT_SCHEMA)).astype(LOT_SCHEMA)
    positions = _positions(lot_frame, last)
    return SimState(trade_frame, lot_frame, positions, _summary(trade_frame, positions, cash, fx, rules, decisions, as_of))


def _positions(lots: pd.DataFrame, last: pd.Series) -> pd.DataFrame:
    if lots.empty:
        return _empty(POSITION_SCHEMA)
    rows = []
    for (wallet, symbol), g in lots.groupby(["wallet", "symbol"], sort=True):
        qty, cost_brl, cost_usdt = float(g["qty"].sum()), float(g["cost_brl"].sum()), float(g["cost_usdt"].sum())
        value_usdt, value_brl = float(g["value_usdt"].sum()), float(g["value_brl"].sum(min_count=1))
        by_brl = math.isfinite(value_brl)
        rows.append({
            "wallet": wallet, "symbol": symbol, "n_lots": len(g), "first_buy": g["exec_day"].min(), "qty": qty,
            "cost_brl": cost_brl, "cost_usdt": cost_usdt, "avg_price_usdt": float(g["paid_usdt"].sum()) / qty,
            "last_close_usdt": _num(last.get(str(symbol))), "value_usdt": value_usdt, "value_brl": value_brl,
            "return_pct": ((value_brl / cost_brl if by_brl else value_usdt / cost_usdt) - 1.0) * 100.0,
            "pnl_brl": value_brl - cost_brl,
        })
    return pd.DataFrame(rows, columns=list(POSITION_SCHEMA)).astype(POSITION_SCHEMA)


def _summary(
    trades: pd.DataFrame, positions: pd.DataFrame, cash: dict[str, float], fx: float, rules: SimRules,
    decisions: pd.DataFrame, as_of: pd.Timestamp,
) -> pd.DataFrame:
    start = pd.Timestamp(decisions["day"].min())
    rows = []
    for wallet in WALLETS:
        pos = positions[positions["wallet"].eq(wallet)]
        mine = trades[trades["wallet"].eq(wallet)]
        usdt = float(pos["value_usdt"].sum())
        brl = usdt * fx if usdt > 0 else 0.0
        total = cash[wallet] + brl
        done = mine["status"].eq(STATUS_DONE)
        rows.append({
            "wallet": wallet, "label": LABELS[wallet], "start": start, "as_of": as_of, "initial_brl": rules.initial_brl,
            "cash_brl": cash[wallet], "positions_usdt": usdt, "positions_brl": brl, "total_brl": total,
            "return_pct": (total / rules.initial_brl - 1.0) * 100.0,
            "n_coins": len(pos), "n_buys": int((done & mine["side"].eq(SIDE_BUY)).sum()),
            "n_sells": int((done & mine["side"].eq(SIDE_SELL)).sum()), "n_pending": int(mine["status"].eq(STATUS_PENDING).sum()),
            "n_not_executed": int(mine["status"].eq(STATUS_NOT_DONE).sum()),
            "currency": CURRENCY_BRL if math.isfinite(fx) else CURRENCY_USDT, "fx_close": fx,
        })
    return pd.DataFrame(rows, columns=list(SUMMARY_SCHEMA)).astype(SUMMARY_SCHEMA)


# ---------------------------------------------------------------------------------------------
# Decisões de cada robô (dados do dia D entram, decisões do dia D saem)
# ---------------------------------------------------------------------------------------------

def _due_sales(wallet: str, day: pd.Timestamp, state: SimState, rules: SimRules) -> list[Row]:
    """Lotes comprados há `hold_days` dias ou mais e ainda sem venda decidida."""
    lots = state.lots[state.lots["wallet"].eq(wallet) & ~state.lots["sale_pending"]].sort_values(["lot_day", "symbol"])
    return [
        (str(r.symbol), SIDE_SELL, _ts(r.lot_day), _num(r.value_brl), f"{rules.hold_days} dias desde a compra")
        for r in lots.itertuples() if (day - _ts(r.lot_day)).days >= rules.hold_days
    ]


def _pending(state: SimState, wallet: str, side: str) -> set[str]:
    t = state.trades
    return set(t.loc[t["wallet"].eq(wallet) & t["side"].eq(side) & t["status"].eq(STATUS_PENDING), "symbol"].astype(str))


def decide_painel(
    day: pd.Timestamp, signals: pd.DataFrame, history: pd.DataFrame, state: SimState,
    available: pd.DataFrame | None = None, rule_table: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Vende a posição inteira quando `advise` devolve VENDER; compra o aporte das moedas selecionadas que a carteira ainda
    não tem (nem com ordem pendente)."""
    lots = state.lots[state.lots["wallet"].eq(PAINEL)]
    held = set(lots["symbol"].astype(str))
    rows: list[Row] = []
    pos = state.positions[state.positions["wallet"].eq(PAINEL)]
    if not pos.empty:
        book = pd.DataFrame({
            "position_id": pos["symbol"].astype("string"), "symbol": pos["symbol"].astype("string"),
            "entry_ts": pos["first_buy"], "entry_price": pos["avg_price_usdt"], "qty": pos["qty"],
        })
        value = dict(zip(pos["symbol"].astype(str), pos["value_brl"], strict=True))
        selling = _pending(state, PAINEL, SIDE_SELL)
        for a in advise(book, history, available=available, rule_table=rule_table).itertuples():
            if str(a.action) == ACTION_SELL and str(a.symbol) not in selling:
                rows.append((str(a.symbol), SIDE_SELL, None, float(value[str(a.symbol)]), f"regra de saída: {a.reason}"))
    skip = held | _pending(state, PAINEL, SIDE_BUY)
    want = signals[signals["selected"].astype(bool) & signals["allocation_brl"].gt(0)].sort_values("candidate_rank")
    rows += [(str(r.symbol), SIDE_BUY, day, _num(r.allocation_brl), "recomendação do painel")
             for r in want.itertuples() if str(r.symbol) not in skip]
    return _bare(PAINEL, day, rows)


def decide_ia(day: pd.Timestamp, log: pd.DataFrame, state: SimState, rules: SimRules = SimRules()) -> pd.DataFrame:
    """As de maior probabilidade do dia (`in_top_k`) no G_GBM, ou no G_GBM_SEM_FNG se o G_GBM não previu hoje; vende os lotes
    de 30 dias."""
    rows: list[Row] = _due_sales(IA, day, state, rules)
    today = log[log["day"].eq(day) & log["in_top_k"].astype(bool)] if not log.empty else log
    for model in (rules.ia_model, rules.ia_fallback):
        picks = today[today["model"].astype(str).eq(model)].sort_values("rank")
        if not picks.empty:
            rows += [(str(r.symbol), SIDE_BUY, day, rules.lot_brl / len(picks), f"{model}, posição {_num(r.rank):.0f}")
                     for r in picks.itertuples()]
            break
    return _bare(IA, day, rows)


def decide_reversal(
    day: pd.Timestamp, panel: Panel, btc_above_sma: bool | None, state: SimState, rules: SimRules = SimRules()
) -> pd.DataFrame:
    """Só com o BTC acima da SMA 200: as `top_k` moedas do universo do dia com o pior retorno de `reversal_days` dias.
    Vende os lotes de 30 dias em qualquer regime."""
    rows: list[Row] = _due_sales(REVERSAO, day, state, rules)
    if btc_above_sma and day in panel.close.index:
        ret = pd.Series(trailing_return(panel.close, rules.reversal_days).loc[day]).where(pd.Series(panel.member.loc[day])).dropna()
        worst = ret.sort_values(kind="stable").head(rules.top_k)
        rows += [(str(s), SIDE_BUY, day, rules.lot_brl / len(worst), f"retorno de {rules.reversal_days} dias {v * 100:+.1f}%")
                 for s, v in worst.items()]
    return _bare(REVERSAO, day, rows)


def decide_btc(day: pd.Timestamp, state: SimState, rules: SimRules = SimRules()) -> pd.DataFrame:
    """Compra o capital inicial em BTC uma vez (tenta de novo só se a compra não foi executada) e nunca vende."""
    t = state.trades
    started = t["wallet"].eq(SO_BTC) & t["side"].eq(SIDE_BUY) & t["status"].isin([STATUS_DONE, STATUS_PENDING])
    if started.any():
        return _bare(SO_BTC, day, [])
    return _bare(SO_BTC, day, [(rules.btc_symbol, SIDE_BUY, day, rules.initial_brl, "compra e segura")])


def decide_all(
    day: pd.Timestamp, *, signals: pd.DataFrame, history: pd.DataFrame, panel: Panel, log: pd.DataFrame, state: SimState,
    available: pd.DataFrame | None = None, rule_table: pd.DataFrame | None = None, rules: SimRules = SimRules(),
) -> pd.DataFrame:
    """Decisões do dia de todos os robôs. `state` é o replay das decisões já gravadas."""
    btc = history[history["symbol"].eq(rules.btc_symbol) & history["timestamp"].eq(day)]
    above = bool(btc["regime_up"].iloc[0]) if not btc.empty and pd.notna(btc["regime_up"].iloc[0]) else None
    parts = [
        decide_painel(day, signals, history, state, available, rule_table),
        decide_ia(day, log, state, rules),
        decide_reversal(day, panel, above, state, rules),
        decide_btc(day, state, rules),
    ]
    return pd.concat([p for p in parts if not p.empty], ignore_index=True) if any(not p.empty for p in parts) else empty_bare()
