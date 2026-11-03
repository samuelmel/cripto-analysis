"""Mensagem do Telegram das carteiras simuladas em reais: agrupamento por moeda, aviso, USDT sem cotação e limite de tamanho."""

from __future__ import annotations

import pandas as pd

from src.transformers.backtest_engine import SIDE_BUY, SIDE_SELL
from src.transformers.notification import format_sim_wallets, validate_messages
from src.transformers.sim_wallet import IA, PAINEL, REVERSAO, SO_BTC, SimState, empty_bare, replay
from tests.test_sim_wallet import _dec, _market

NOW = pd.Timestamp("2026-02-01 21:07", tz="UTC")
COINS4 = ("BTC/USDT", "SOL/USDT", "ETH/USDT", "ADA/USDT")


def _text(state: SimState) -> str:
    texts = format_sim_wallets(state.summary, state.positions, state.trades, now=NOW)
    assert validate_messages(texts) == []
    return "\n".join(texts)


def _scenario_state(**market_kwargs: object) -> SimState:
    market = _market(n=32, coins=COINS4, close_from={"SOL/USDT": (20, 108.0), "ETH/USDT": (20, 95.0), "ADA/USDT": (20, 80.0)}, **market_kwargs)  # type: ignore[arg-type]
    decisions = _dec([
        (PAINEL, 10, "SOL/USDT", SIDE_BUY, 15.0), (PAINEL, 10, "ETH/USDT", SIDE_BUY, 30.0), (PAINEL, 10, "ADA/USDT", SIDE_BUY, 15.0),
        (PAINEL, 30, "ADA/USDT", SIDE_SELL, 12.0), (PAINEL, 31, "SOL/USDT", SIDE_SELL, 16.0),
        (IA, 5, "SOL/USDT", SIDE_BUY, 6.67), (IA, 6, "SOL/USDT", SIDE_BUY, 6.67), (IA, 6, "ETH/USDT", SIDE_BUY, 6.67),
        (SO_BTC, 1, "BTC/USDT", SIDE_BUY, 1000.0),
    ])
    return replay(decisions, market)


def test_message_shows_each_wallet_by_coin_with_sales_cash_pending_orders_and_the_simulation_warning() -> None:
    text = _text(_scenario_state())
    assert text.startswith("💼 CARTEIRAS SIMULADAS (dinheiro fictício, sem ordens reais)")
    assert "Recomendação do painel: R$ 1.000,00 → R$" in text and "IA (boosting): R$ 1.000,00 → R$" in text
    assert "Reversão (experimental, sem estudo): R$ 1.000,00 → R$ 1.000,00 (+0,0%)" in text and "Só BTC (referência): R$ 1.000,00 →" in text
    assert "  ETH  comprou 12/01 R$ 30,00 → hoje R$" in text and "↓" in text
    assert "  SOL  2 lotes desde 07/01" in text  # os lotes da IA aparecem agrupados por moeda
    assert "  ADA  vendeu 01/02 por R$" in text and "(comprou R$ 15,00:" in text
    assert "Na abertura de amanhã: vender SOL" in text and "Em caixa: R$" in text
    assert "dinheiro fictício, não é recomendação; nenhuma ordem real" in text and "Reversão não foi estudada" in text


def test_message_without_the_real_quote_shows_usdt_with_a_warning() -> None:
    text = _text(_scenario_state(fx_close=None))
    assert "cotação do real indisponível: valores em USDT" in text and "USDT" in text
    assert "R$ 1.000,00 →" not in text.split("Só BTC")[0].split("Recomendação do painel")[1][:40]  # sem total em reais


def test_message_with_many_coins_is_split_under_the_telegram_limit() -> None:
    coins = tuple(f"M{i:02d}/USDT" for i in range(60))
    market = _market(n=40, coins=("BTC/USDT", *coins))
    rows = [(w, 5, c, SIDE_BUY, 6.0) for w in (IA, REVERSAO) for c in coins[:30]]
    state = replay(_dec(rows), market)
    texts = format_sim_wallets(state.summary, state.positions, state.trades, now=NOW)
    assert validate_messages(texts) == [] and all(len(t) <= 4096 for t in texts)
    assert "+ 20 moedas" in "\n".join(texts)  # mostra as 10 maiores e resume o resto


def test_message_is_empty_before_the_first_decision() -> None:
    state = replay(empty_bare(), _market())
    assert format_sim_wallets(state.summary, state.positions, state.trades, now=NOW) == []
