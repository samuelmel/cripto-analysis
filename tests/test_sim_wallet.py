"""Carteiras simuladas em reais: execução na abertura seguinte, caixa, lotes de 30 dias, cotação do real e registro."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.loaders.sim_wallet_store import SimLogIntegrityError, append_decisions, read_decisions
from src.transformers.backtest_engine import SIDE_BUY, SIDE_SELL
from src.transformers.costs import CostModel
from src.transformers.entry_signals import Panel
from src.transformers.sim_wallet import (
    BARE_COLUMNS,
    DECISION_SCHEMA,
    IA,
    PAINEL,
    REVERSAO,
    SO_BTC,
    STATUS_DONE,
    STATUS_NOT_DONE,
    STATUS_PENDING,
    SimMarket,
    SimRules,
    SimState,
    chain_rows,
    empty_log,
    decide_btc,
    decide_ia,
    decide_painel,
    decide_reversal,
    empty_bare,
    replay,
    stamp,
    verify_chain,
    with_new,
)

COSTS = CostModel()
HALF = 0.0005
START = pd.Timestamp("2026-01-01", tz="UTC")


def _market(
    n: int = 90, *, coins: Sequence[str] = ("BTC/USDT", "AAA/USDT", "BBB/USDT"), price: float = 100.0,
    open_at: dict[str, dict[int, float]] | None = None, close_from: dict[str, tuple[int, float]] | None = None,
    fx: float | None = 5.0, fx_close: float | None = 5.0,
) -> SimMarket:
    """Mercado plano: abertura = fechamento = `price`, salvo `open_at` (abertura de um dia) e `close_from` (a partir de um
    dia, abertura e fechamento mudam)."""
    index = pd.date_range(START, periods=n, freq="D")
    op = pd.DataFrame(price, index=index, columns=list(coins))
    cl = op.copy()
    for symbol, (day, value) in (close_from or {}).items():
        op.iloc[day:, op.columns.get_loc(symbol)] = value
        cl.iloc[day:, cl.columns.get_loc(symbol)] = value
    for symbol, days in (open_at or {}).items():
        for day, value in days.items():
            op.iloc[day, op.columns.get_loc(symbol)] = value
    half = pd.DataFrame(HALF, index=index, columns=list(coins))
    nan = float("nan")
    return SimMarket(op, cl, half, pd.Series(nan if fx is None else fx, index=index), pd.Series(nan if fx_close is None else fx_close, index=index), COSTS)


def _upto(market: SimMarket, day: pd.Timestamp) -> SimMarket:
    return dataclasses.replace(
        market, open=market.open.loc[:day], close=market.close.loc[:day], half_spread=market.half_spread.loc[:day],
        fx_open=market.fx_open.loc[:day], fx_close=market.fx_close.loc[:day],
    )


def _day(i: int) -> pd.Timestamp:
    return START + pd.Timedelta(days=i)


def _dec(rows: Sequence[tuple[str, int, str, str, float]]) -> pd.DataFrame:
    """(carteira, dia, moeda, lado, valor) -> decisões no formato do registro; o lote de uma compra é o próprio dia."""
    frame = pd.DataFrame({
        "wallet": [r[0] for r in rows], "day": [_day(r[1]) for r in rows], "symbol": [r[2] for r in rows],
        "side": [r[3] for r in rows], "lot_day": pd.to_datetime([_day(r[1]) if r[3] == SIDE_BUY else pd.NaT for r in rows], utc=True),
        "amount_brl": [r[4] for r in rows], "reason": "teste",
    })
    return frame.astype({c: DECISION_SCHEMA[c] for c in BARE_COLUMNS})


def _drive(market: SimMarket, days: Sequence[pd.Timestamp], decide: Callable[[pd.Timestamp, SimState], pd.DataFrame]) -> tuple[pd.DataFrame, SimState]:
    """Um dia de cada vez, como o pipeline: replay do que está gravado, decisões do dia, grava (sem repetir chave)."""
    decisions = empty_bare()
    for d in days:
        state = replay(decisions, _upto(market, d))
        assert state.summary.empty or (state.summary["cash_brl"] >= -1e-9).all()  # nunca caixa negativo
        decisions = with_new(decisions, decide(d, state))
    return decisions, replay(decisions, _upto(market, days[-1]))


# --- execução ----------------------------------------------------------------------------------

def test_buy_decided_on_d_fills_at_the_open_of_d_plus_1_with_costs_never_at_the_close_of_d() -> None:
    market = _market(open_at={"AAA/USDT": {11: 110.0}})  # fechamento de D = 100; abertura de D+1 = 110
    state = replay(_dec([(PAINEL, 10, "AAA/USDT", SIDE_BUY, 100.0)]), market)
    t = state.trades.iloc[0]
    fill = 110.0 * (1.0 + HALF + COSTS.slippage)
    assert t["status"] == STATUS_DONE and t["exec_day"] == _day(11)
    assert t["price_usdt"] == pytest.approx(fill) and t["price_usdt"] > 110.0  # abertura + spread + slippage
    assert t["qty"] == pytest.approx(100.0 / (1.0 + COSTS.fee_rate) / 5.0 / fill)
    assert t["fee_brl"] == pytest.approx(100.0 - 100.0 / (1.0 + COSTS.fee_rate)) and t["fx"] == 5.0
    w = state.summary.set_index("wallet").loc[PAINEL]
    assert w["cash_brl"] == pytest.approx(900.0)
    assert w["positions_brl"] == pytest.approx(t["qty"] * 100.0 * 5.0)  # valor do dia: quantidade × fechamento × cotação


def test_decision_of_the_last_day_waits_for_the_next_open() -> None:
    market = _market(n=11)  # o último candle é o dia 10
    state = replay(_dec([(PAINEL, 10, "AAA/USDT", SIDE_BUY, 100.0)]), market)
    assert state.trades["status"].tolist() == [STATUS_PENDING]
    assert state.lots.empty and state.summary.set_index("wallet").loc[PAINEL, "cash_brl"] == 1000.0


def test_cash_never_goes_negative_and_a_buy_without_cash_is_recorded_as_not_executed() -> None:
    market = _market()
    state = replay(_dec([(PAINEL, 10, "AAA/USDT", SIDE_BUY, 600.0), (PAINEL, 10, "BBB/USDT", SIDE_BUY, 600.0)]), market)
    by_symbol = state.trades.set_index("symbol")
    assert by_symbol.loc["AAA/USDT", "status"] == STATUS_DONE
    assert by_symbol.loc["BBB/USDT", "status"] == STATUS_NOT_DONE and by_symbol.loc["BBB/USDT", "reason"] == "caixa insuficiente"
    summary = state.summary.set_index("wallet").loc[PAINEL]
    assert summary["cash_brl"] == pytest.approx(400.0) and summary["n_not_executed"] == 1 and summary["n_coins"] == 1


def test_sale_proceeds_come_back_to_cash_with_costs_and_sell_before_buy_on_the_same_day() -> None:
    market = _market(close_from={"AAA/USDT": (20, 120.0)})
    decisions = _dec([
        (PAINEL, 10, "AAA/USDT", SIDE_BUY, 1000.0),   # gasta todo o caixa
        (PAINEL, 30, "AAA/USDT", SIDE_SELL, 0.0),
        (PAINEL, 30, "BBB/USDT", SIDE_BUY, 500.0),    # só cabe com o dinheiro da venda
    ])
    state = replay(decisions, market)
    sale = state.trades[state.trades["side"].eq(SIDE_SELL)].iloc[0]
    assert sale["status"] == STATUS_DONE and sale["return_pct"] > 0 and sale["value_brl"] > 1000.0
    assert state.trades[state.trades["symbol"].eq("BBB/USDT")]["status"].iloc[0] == STATUS_DONE
    assert state.lots["symbol"].tolist() == ["BBB/USDT"]


# --- IA e REVERSAO: lotes de 30 dias; SO_BTC: nunca vende -----------------------------------------

def _ia_log(days: range, symbols: Sequence[str], model: str = "G_GBM") -> pd.DataFrame:
    rows = [{"day": _day(d), "symbol": s, "model": model, "rank": i + 1, "in_top_k": i < 5} for d in days for i, s in enumerate(symbols)]
    return pd.DataFrame(rows)


COINS6 = tuple(f"C{i}/USDT" for i in range(6))


def test_ia_buys_the_top_five_with_a_thirtieth_of_the_capital_and_sells_each_lot_after_thirty_days() -> None:
    market = _market(coins=("BTC/USDT", *COINS6))
    log = _ia_log(range(0, 60), COINS6)
    decisions, state = _drive(market, [_day(i) for i in range(0, 36)], lambda d, s: decide_ia(d, log, s))
    first = decisions[decisions["day"].eq(_day(0))]
    assert len(first) == 5 and first["side"].eq(SIDE_BUY).all() and first["amount_brl"].sum() == pytest.approx(1000.0 / 30)
    assert "C5/USDT" not in set(decisions["symbol"])  # só o top 5
    sells = decisions[decisions["side"].eq(SIDE_SELL)]
    assert sells["day"].min() == _day(30)  # nada sai antes de 30 dias
    assert sells[sells["day"].eq(_day(30))]["lot_day"].eq(_day(0)).all() and (sells["day"] - sells["lot_day"]).eq(pd.Timedelta(days=30)).all()
    done = state.trades[state.trades["side"].eq(SIDE_SELL) & state.trades["status"].eq(STATUS_DONE)]
    assert not done.empty and done["exec_day"].min() == _day(31)  # decidida em D+30, executada na abertura de D+31
    assert state.lots["lot_day"].min() > _day(0)  # o lote do dia 0 já saiu


def test_ia_falls_back_to_the_model_without_fear_and_greed_when_the_main_model_is_missing() -> None:
    log = pd.concat([_ia_log(range(0, 1), COINS6, "G_GBM_SEM_FNG"), _ia_log(range(1, 2), COINS6, "G_GBM")], ignore_index=True)
    state = replay(empty_bare(), _market(coins=("BTC/USDT", *COINS6)))
    day0, day1 = decide_ia(_day(0), log, state), decide_ia(_day(1), log, state)
    assert day0["reason"].str.startswith("G_GBM_SEM_FNG").all() and len(day0) == 5
    assert day1["reason"].str.startswith("G_GBM,").all()
    assert decide_ia(_day(2), log, state).empty  # sem previsão no dia: nada a comprar


def _panel(n: int = 120, growth: Sequence[float] = (-0.004, -0.003, -0.002, -0.001, 0.0, 0.001, 0.002, 0.003)) -> Panel:
    index = pd.date_range(START, periods=n, freq="D")
    coins = [f"R{i}/USDT" for i in range(len(growth))]
    close = pd.DataFrame({c: 100.0 * (1.0 + g) ** np.arange(n) for c, g in zip(coins, growth, strict=True)}, index=index)
    member = pd.DataFrame(True, index=index, columns=coins)
    return Panel(close, close, close * 0 + 1e9, member, close * 0 + 0.002, ())


def test_reversal_buys_the_five_worst_ninety_day_returns_only_with_btc_above_the_sma_200() -> None:
    panel, day = _panel(), _day(100)
    state = replay(empty_bare(), _market(coins=("BTC/USDT",)))
    up = decide_reversal(day, panel, True, state)
    assert up["symbol"].tolist() == [f"R{i}/USDT" for i in range(5)] and up["side"].eq(SIDE_BUY).all()
    assert up["amount_brl"].sum() == pytest.approx(1000.0 / 30)
    assert decide_reversal(day, panel, False, state).empty  # BTC abaixo da SMA 200
    assert decide_reversal(day, panel, None, state).empty   # regime desconhecido: não compra
    out = dataclasses.replace(panel, member=panel.member.assign(**{"R0/USDT": False}))
    assert decide_reversal(day, out, True, state)["symbol"].tolist() == [f"R{i}/USDT" for i in range(1, 6)]  # fora do universo do dia


def test_reversal_lots_leave_after_thirty_days_even_when_the_regime_turns_down() -> None:
    panel = _panel(160)
    market = _market(n=160, coins=("BTC/USDT", *panel.close.columns))
    held, _ = _drive(market, [_day(i) for i in range(95, 100)], lambda d, s: decide_reversal(d, panel, True, s))
    assert len(held) == 25  # 5 dias com o BTC em alta, 5 moedas por dia
    sells = decide_reversal(_day(125), panel, False, replay(held, _upto(market, _day(125))))  # o BTC está abaixo da SMA 200
    assert set(sells["lot_day"]) == {_day(95)} and sells["side"].eq(SIDE_SELL).all() and len(sells) == 5
    assert decide_reversal(_day(124), panel, False, replay(held, _upto(market, _day(124)))).empty  # com 29 dias, nada sai


def test_buy_and_hold_btc_buys_once_and_never_sells() -> None:
    market = _market(n=120)
    decisions, state = _drive(market, [_day(i) for i in range(0, 100)], lambda d, s: decide_btc(d, s))
    assert len(decisions) == 1 and decisions["side"].eq(SIDE_BUY).all() and decisions["amount_brl"].iloc[0] == 1000.0
    assert state.lots["symbol"].tolist() == ["BTC/USDT"] and not state.trades["side"].eq(SIDE_SELL).any()


def test_buy_and_hold_btc_tries_again_if_the_first_buy_was_not_executed() -> None:
    market = _market(n=12, fx=None, fx_close=None)  # sem cotação do real: a compra não executa
    decisions = _dec([(SO_BTC, 3, "BTC/USDT", SIDE_BUY, 1000.0)])
    state = replay(decisions, market)
    assert state.trades["status"].tolist() == [STATUS_NOT_DONE]
    assert len(decide_btc(_day(11), state)) == 1


# --- PAINEL -----------------------------------------------------------------------------------------

def _history(market: SimMarket, sma: float = 90.0) -> pd.DataFrame:
    rows = [{"symbol": s, "timestamp": ts, "close": float(v), "sma_200": sma, "regime_up": True}
            for s in market.close.columns for ts, v in market.close[s].items()]
    return pd.DataFrame(rows)


def _signals(selected: Sequence[str], allocation: float = 15.0) -> pd.DataFrame:
    return pd.DataFrame({"symbol": list(selected), "selected": True, "allocation_brl": allocation, "candidate_rank": range(1, len(selected) + 1)})


def test_painel_buys_the_recommendation_once_sells_the_whole_position_on_vender_and_does_not_rebuy_while_holding() -> None:
    market = _market(close_from={"AAA/USDT": (20, 80.0)})  # a partir do dia 20 fecha abaixo da SMA 200 (90)

    def decide(d: pd.Timestamp, state: SimState) -> pd.DataFrame:
        selected = ["AAA/USDT"] if d < _day(20) else []
        return decide_painel(d, _signals(selected), _history(_upto(market, d)), state)

    days = [_day(i) for i in range(10, 30)]
    decisions, state = _drive(market, days, decide)
    buys, sells = decisions[decisions["side"].eq(SIDE_BUY)], decisions[decisions["side"].eq(SIDE_SELL)]
    assert buys["day"].tolist() == [_day(10)] and buys["amount_brl"].tolist() == [15.0]  # 10 dias selecionada, uma compra só
    assert sells["day"].tolist() == [_day(20)] and sells["symbol"].tolist() == ["AAA/USDT"]
    assert state.lots.empty and state.trades["status"].eq(STATUS_DONE).all()
    # rodar o mesmo dia de novo não cria ordem repetida (a ordem pendente conta)
    again = decide_painel(_day(20), _signals([]), _history(_upto(market, _day(20))), replay(decisions[decisions["day"].le(_day(20))], _upto(market, _day(20))))
    assert again.empty
    held = replay(buys, _upto(market, _day(11)))
    assert decide_painel(_day(11), _signals(["AAA/USDT"]), _history(_upto(market, _day(11))), held).empty


def test_painel_keeps_a_position_that_has_no_exit_rule_firing() -> None:
    market = _market()
    decisions, state = _drive(market, [_day(i) for i in range(10, 25)], lambda d, s: decide_painel(d, _signals(["AAA/USDT"]), _history(_upto(market, d)), s))
    assert len(decisions) == 1 and not state.trades["side"].eq(SIDE_SELL).any() and state.lots["symbol"].tolist() == ["AAA/USDT"]


# --- cotação do real -------------------------------------------------------------------------------------

def test_without_a_usdt_brl_quote_the_buy_is_not_executed_and_nothing_is_invented() -> None:
    state = replay(_dec([(PAINEL, 10, "AAA/USDT", SIDE_BUY, 100.0)]), _market(fx=None, fx_close=None))
    t = state.trades.iloc[0]
    assert t["status"] == STATUS_NOT_DONE and "cotação do real" in str(t["reason"])
    assert state.summary.set_index("wallet").loc[PAINEL, "cash_brl"] == 1000.0


def test_without_a_quote_on_the_valuation_day_values_come_out_in_usdt() -> None:
    market = _market(fx=5.0, fx_close=None)  # a execução teve cotação; o dia da avaliação, não
    state = replay(_dec([(PAINEL, 10, "AAA/USDT", SIDE_BUY, 100.0)]), market)
    w = state.summary.set_index("wallet").loc[PAINEL]
    assert w["currency"] == "USDT" and np.isnan(w["total_brl"]) and np.isnan(w["return_pct"])
    assert w["positions_usdt"] > 0 and w["cash_brl"] == pytest.approx(900.0)
    pos = state.positions.iloc[0]
    assert np.isnan(pos["value_brl"]) and np.isfinite(pos["value_usdt"]) and np.isfinite(pos["return_pct"])  # retorno em USDT


# --- replay e registro ---------------------------------------------------------------------------------------

def test_replay_is_deterministic_regardless_of_the_order_the_decisions_arrive() -> None:
    market = _market(close_from={"AAA/USDT": (15, 120.0)})
    decisions = _dec([
        (IA, 5, "AAA/USDT", SIDE_BUY, 6.67), (IA, 5, "BBB/USDT", SIDE_BUY, 6.67), (PAINEL, 6, "BBB/USDT", SIDE_BUY, 15.0),
        (PAINEL, 20, "BBB/USDT", SIDE_SELL, 0.0), (SO_BTC, 1, "BTC/USDT", SIDE_BUY, 1000.0),
    ])
    first, second = replay(decisions, market), replay(decisions.sample(frac=1.0, random_state=3), market)
    for a, b in ((first.trades, second.trades), (first.positions, second.positions), (first.summary, second.summary)):
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
    pd.testing.assert_frame_equal(first.summary, replay(decisions, market).summary)


def _stamped(rows: Sequence[tuple[str, int, str, str, float]]) -> pd.DataFrame:
    return stamp(_dec(rows), run_ts=pd.Timestamp("2026-03-01", tz="UTC"), code_version="abc")


def test_decision_log_is_append_only_idempotent_per_key_and_tamper_evident() -> None:
    day1 = _stamped([(PAINEL, 1, "AAA/USDT", SIDE_BUY, 15.0), (IA, 1, "BBB/USDT", SIDE_BUY, 6.67)])
    log = chain_rows(empty_log(), day1)
    assert len(log) == 2 and verify_chain(log) == []
    assert chain_rows(log, day1).empty  # mesmo dia de novo: nada novo
    changed = _stamped([(PAINEL, 1, "AAA/USDT", SIDE_BUY, 99.0)])
    assert chain_rows(log, changed).empty  # chave existente nunca é reescrita
    day2 = chain_rows(log, _stamped([(PAINEL, 2, "AAA/USDT", SIDE_SELL, 16.0)]))
    full = pd.concat([log, day2], ignore_index=True)
    assert verify_chain(full) == [] and day2["prev_hash"].iloc[0] == log["row_hash"].iloc[-1]
    forged = full.copy()
    forged.loc[0, "amount_brl"] = 999.0
    assert any("alterado" in p for p in verify_chain(forged))
    assert verify_chain(full.iloc[1:].reset_index(drop=True))  # linha apagada quebra a cadeia


def test_new_decisions_do_not_repeat_a_key_already_stored() -> None:
    stored = _dec([(PAINEL, 1, "AAA/USDT", SIDE_BUY, 15.0)])
    merged = with_new(stored, _dec([(PAINEL, 1, "AAA/USDT", SIDE_BUY, 99.0), (PAINEL, 1, "BBB/USDT", SIDE_BUY, 15.0)]))
    assert len(merged) == 2 and merged.loc[merged["symbol"].eq("AAA/USDT"), "amount_brl"].iloc[0] == 15.0


def test_loader_appends_once_per_key_and_refuses_a_tampered_file(tmp_path: Path) -> None:
    path = tmp_path / "state" / "sim_decisions.parquet"
    assert read_decisions(path).empty
    day1 = _stamped([(PAINEL, 1, "AAA/USDT", SIDE_BUY, 15.0), (IA, 1, "BBB/USDT", SIDE_BUY, 6.67)])
    assert append_decisions(day1, path) == 2
    assert append_decisions(day1, path) == 0  # mesmo dia: idempotente
    assert append_decisions(_stamped([(PAINEL, 2, "AAA/USDT", SIDE_SELL, 16.0)]), path) == 1
    stored = read_decisions(path)
    assert len(stored) == 3 and verify_chain(stored) == [] and stored["day"].is_monotonic_increasing
    forged = stored.copy()
    forged.loc[0, "amount_brl"] = 1.0
    forged.to_parquet(path, index=False)
    with pytest.raises(SimLogIntegrityError):
        append_decisions(_stamped([(PAINEL, 3, "AAA/USDT", SIDE_BUY, 15.0)]), path)
    assert len(pd.read_parquet(path)) == 3  # nada foi gravado

