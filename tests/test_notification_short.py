"""Mensagem curta do Telegram: limite de tamanho, linguagem simples e avisos só quando algo mudou."""

from __future__ import annotations

import pandas as pd

from src.transformers.notification import validate_messages
from src.transformers.notification_short import SHORT_LIMIT, format_short_report
from tests.test_notifications import LAST, NOW, coin, pick, rec, signals

SUMMARY = pd.DataFrame({
    "wallet": ["PAINEL", "IA", "REVERSAO", "SO_BTC"], "return_pct": [12.0, 8.04, -3.0, 15.26],
})


def short(sig: pd.DataFrame, recommendation: pd.DataFrame, **kwargs: object) -> str:
    texts = format_short_report(sig, recommendation, now=NOW, **kwargs)  # type: ignore[arg-type]
    assert len(texts) == 1
    assert validate_messages(texts) == []
    assert len(texts[0]) <= SHORT_LIMIT
    return texts[0]


def market(close: float = 112.0, sma: float = 100.0, regime: str = "FAVORAVEL") -> pd.DataFrame:
    return rec(regime=regime, regime_close=close, regime_sma_200=sma)


def test_example_message_is_one_short_message_in_plain_portuguese() -> None:
    sig = signals(pick("NEAR/USDT", 1, 10.0), pick("SOL/USDT", 2, 20.0), pick("BTC/USDT", 3, 20.0), coin("ETH/USDT"))
    text = short(sig, market().assign(total_brl=50.0), sim_summary=SUMMARY)
    assert text.startswith("📊 Cripto hoje (15/10)")
    assert "Mercado: em alta 🟢 (BTC 12% acima da média de 200 dias)" in text
    assert "Hoje: aporte simulado de R$ 50 em NEAR, SOL, BTC" in text
    assert "Carteiras simuladas (desde o início): Regra +12,0% · IA (em teste) +8,0% · Só segurar BTC +15,3%" in text
    assert "Reversão" not in text and "REVERSAO" not in text
    assert text.endswith("Detalhes no painel. Simulação, não é recomendação.")


def test_nothing_to_do_and_nothing_changed_has_no_warnings() -> None:
    text = short(signals(coin("BTC/USDT")), market(), sim_summary=SUMMARY, previous_regime="FAVORAVEL")
    assert "Hoje: nada a fazer" in text
    assert "Mudou" not in text and "⚠️" not in text


def test_below_the_average_is_called_down_market() -> None:
    text = short(signals(coin("BTC/USDT")), market(close=90.0, regime="DEFENSIVO"), previous_regime="DEFENSIVO")
    assert "em baixa 🔴 (BTC 10% abaixo da média de 200 dias)" in text


def test_regime_change_is_the_only_extra_warning() -> None:
    text = short(signals(coin("BTC/USDT")), market(close=90.0, regime="DEFENSIVO"), previous_regime="FAVORAVEL")
    assert "⚠️ Mudou: o mercado virou para baixa." in text
    assert text.count("⚠️") == 1


def test_position_entry_and_stale_data_warnings() -> None:
    stale = market().assign(data_day=LAST - pd.Timedelta(days=2))
    text = short(signals(coin("BTC/USDT")), stale, n_position_changes=1, n_entry_changes=2)
    assert "uma posição sua mudou de estado" in text
    assert "novo sinal de entrada" in text
    assert "Dados atrasados 2 dia(s)." in text


def test_many_picks_are_summarized_not_listed() -> None:
    rows = [pick(f"C{i}/USDT", i, 5.0) for i in range(1, 9)]
    text = short(signals(*rows), market().assign(total_brl=40.0))
    assert "e mais 5" in text


def test_ai_line_is_shown_when_it_fits() -> None:
    text = short(signals(coin("BTC/USDT")), market(), ai_line="IA (em teste): sem opinião hoje")
    assert "IA (em teste): sem opinião hoje" in text


def test_absurdly_long_input_is_still_cut_to_the_limit() -> None:
    rows = [pick(f"MOEDA{i}/USDT", i, 5.0) for i in range(1, 9)]
    text = short(signals(*rows), market(close=90.0, regime="DEFENSIVO").assign(total_brl=40.0), sim_summary=SUMMARY,
                 previous_regime="FAVORAVEL", n_position_changes=1, n_entry_changes=1, ai_line="IA " + "x" * 700)
    assert len(text) <= SHORT_LIMIT


def test_missing_data_is_not_shown_as_a_number() -> None:
    text = short(signals(coin("BTC/USDT")), market(close=float("nan"), sma=float("nan"), regime="INDISPONIVEL"))
    assert "Mercado: sem dados ⚪" in text
    assert "nan" not in text.lower()


def test_no_simulated_wallets_means_no_wallet_line() -> None:
    assert "Carteiras" not in short(signals(coin("BTC/USDT")), market(), sim_summary=None)
