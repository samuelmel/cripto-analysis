"""Qualidade dos dados: auditoria, limpeza, dado desatualizado e universo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.anomaly_detector import OUTPUT_SCHEMA, STAGE_BUY, STAGE_UNAVAILABLE, classify_history, detect
from src.transformers.daily_alerts import compare_with_previous
from src.transformers.data_quality import audit_candles, availability, clean_candles, mark_unavailable
from src.transformers.universe import UniverseRules, select_universe
from tests.helpers import make_candles, ramp

NO_FNG = pd.DataFrame()
TODAY = pd.Timestamp("2026-07-01", tz="UTC")  # último candle fechado esperado: 2026-06-30


def kinds(issues: pd.DataFrame, symbol: str = "BTC/USDT") -> dict[str, int]:
    part = issues[issues["symbol"].eq(symbol)]
    return dict(zip(part["kind"], part["count"], strict=True))


def test_audit_finds_each_problem() -> None:
    candles = make_candles({"BTC/USDT": ramp(100, 110, 10)})
    dup = pd.concat([candles, candles.iloc[[3]]], ignore_index=True)  # duplicado, e fora de ordem no fim
    dup.loc[1, "close"] = np.nan
    dup.loc[2, "close"] = np.inf
    dup.loc[4, "close"] = 0.0
    dup.loc[5, "close"] = -3.0
    dup = dup.drop(index=7)  # lacuna de um dia
    found = kinds(audit_candles(dup))
    assert found["duplicados"] == 1
    assert found["fora_de_ordem"] == 1
    assert found["preco_invalido"] == 4
    assert found["lacunas"] == 1


def test_audit_flags_mixed_sources_and_is_empty_when_clean() -> None:
    clean = make_candles({"BTC/USDT": ramp(100, 110, 10)})
    assert audit_candles(clean).empty
    other = make_candles({"BTC/USDT": ramp(100, 110, 10)}, source="outra")
    mixed = pd.concat([clean.iloc[:5], other.iloc[5:]], ignore_index=True)
    assert kinds(audit_candles(mixed))["fontes_misturadas"] == 1


def test_clean_candles_drops_invalid_and_duplicates() -> None:
    candles = make_candles({"BTC/USDT": [100.0, np.nan, 102.0, np.inf, 104.0, 0.0]})
    cleaned = clean_candles(pd.concat([candles, candles.iloc[[0]]], ignore_index=True))
    assert cleaned["close"].tolist() == [100.0, 102.0, 104.0]
    assert cleaned["timestamp"].is_monotonic_increasing


def _history(btc: list[float], eth: list[float], end: str = "2026-06-30") -> pd.DataFrame:
    return classify_history(make_candles({"BTC/USDT": btc, "ETH/USDT": eth}, end), NO_FNG)


def test_fresh_data_is_available() -> None:
    history = _history(ramp(100, 200, 250), ramp(50, 150, 250))
    avail = availability(history, ("BTC/USDT", "ETH/USDT"), TODAY)
    assert avail["available"].all()
    assert avail["reason"].isna().all()


def test_stale_data_boundary() -> None:
    btc, eth = ramp(100, 200, 250), ramp(50, 150, 250)
    one_day_late = availability(_history(btc, eth, "2026-06-29"), ("BTC/USDT", "ETH/USDT"), TODAY)
    assert one_day_late["available"].all()  # 1 dia de atraso ainda é tolerado
    two_days_late = availability(_history(btc, eth, "2026-06-28"), ("BTC/USDT", "ETH/USDT"), TODAY)
    assert not two_days_late["available"].any()
    assert "desatualizado" in two_days_late["reason"].iloc[0]
    assert "28/06/2026" in two_days_late["reason"].iloc[0]


def test_long_gap_flags_a_possible_delisting_without_assuming_the_cause() -> None:
    btc, eth = ramp(100, 200, 250), ramp(50, 150, 250)
    month_late = availability(_history(btc, eth, "2026-05-30"), ("BTC/USDT", "ETH/USDT"), TODAY)  # 31 dias de atraso
    reason = month_late["reason"].iloc[0]
    assert not month_late["available"].any() and "desatualizado" in reason
    assert "possível deslistagem" in reason and "causa não verificada" in reason
    assert "perda" not in reason  # nunca presume perda total
    short = availability(_history(btc, eth, "2026-06-20"), ("BTC/USDT", "ETH/USDT"), TODAY)  # 10 dias: só desatualizada
    assert "desatualizado" in short["reason"].iloc[0] and "deslistagem" not in short["reason"].iloc[0]


def test_stale_btc_makes_other_coins_unavailable() -> None:
    btc = make_candles({"BTC/USDT": ramp(100, 200, 250)}, "2026-06-20")
    eth = make_candles({"ETH/USDT": ramp(50, 150, 250)}, "2026-06-30")
    history = classify_history(pd.concat([btc, eth], ignore_index=True), NO_FNG)
    avail = availability(history, ("BTC/USDT", "ETH/USDT"), TODAY).set_index("symbol")
    assert not avail.loc["BTC/USDT", "available"]
    assert not avail.loc["ETH/USDT", "available"]
    assert "filtro de mercado" in avail.loc["ETH/USDT", "reason"]


def test_insufficient_history_is_unavailable() -> None:
    history = _history(ramp(100, 200, 250), ramp(50, 60, 120))
    avail = availability(history, ("BTC/USDT", "ETH/USDT"), TODAY).set_index("symbol")
    assert avail.loc["BTC/USDT", "available"]
    assert "histórico insuficiente" in avail.loc["ETH/USDT", "reason"]


def test_stale_snapshot_never_gives_a_current_signal() -> None:
    candles = make_candles({"BTC/USDT": ramp(100, 200, 250), "ETH/USDT": ramp(50, 150, 250)}, "2026-06-20")
    history = classify_history(candles, NO_FNG)
    assert (history.groupby("symbol")["stage"].last() == STAGE_BUY).all()  # o histórico até 20/06 era de compra

    snapshot = detect(candles, pd.DataFrame(), NO_FNG, history=history)
    marked = mark_unavailable(snapshot, availability(history, ("BTC/USDT", "ETH/USDT"), TODAY))
    assert (marked["stage"] == STAGE_UNAVAILABLE).all()
    assert marked["stage_reason"].str.contains("desatualizado").all()
    assert not marked["panic"].any()
    assert not marked["uptrend"].any()
    assert set(OUTPUT_SCHEMA) <= set(marked.columns)

    previous = snapshot.assign(stage=STAGE_BUY)  # ontem estavam em COMPRAR
    alerts = compare_with_previous(marked, previous)
    assert alerts["alert"].isna().all()  # dado velho não gera "VENDER AGORA" nem qualquer outro alerta


def test_detect_without_coingecko_has_null_market_cap() -> None:
    candles = make_candles({"BTC/USDT": ramp(100, 200, 250)})
    snapshot = detect(candles, pd.DataFrame(), NO_FNG)
    assert snapshot["market_cap_usd"].isna().all()
    assert snapshot["stage_reason"].isna().all()


def _universe_candles() -> pd.DataFrame:
    days = 400
    series = {s: ramp(10, 20, days) for s in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "NEW/USDT", "THIN/USDT")}
    candles = make_candles(series)
    candles.loc[candles["symbol"].eq("THIN/USDT"), "quote_volume"] = 10.0
    return candles[~(candles["symbol"].eq("NEW/USDT") & (candles["timestamp"] < candles["timestamp"].max() - pd.Timedelta(days=100)))]


CANDIDATES = {
    "BTC/USDT": "bitcoin", "ETH/USDT": "ethereum", "SOL/USDT": "solana", "ADA/USDT": "cardano",
    "NEW/USDT": "new", "THIN/USDT": "thin", "USDC/USDT": "usd-coin", "BTCUP/USDT": "btcup",
    "SOL2/USDT": "solana", "WBTC/USDT": "wrapped-bitcoin",
}


def test_universe_selection_documents_every_exclusion() -> None:
    rules = UniverseRules(recommended=("BTC/USDT", "ETH/USDT"), max_extra=2, min_history_days=365)
    chosen = select_universe(CANDIDATES, _universe_candles(), rules)
    assert chosen.kept == ("BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT")
    assert "stablecoin" in chosen.dropped["USDC/USDT"]
    assert chosen.dropped["BTCUP/USDT"] == "token alavancado"
    assert chosen.dropped["SOL2/USDT"] == "duplicada"
    assert "duplicata do BTC" in chosen.dropped["WBTC/USDT"]
    assert "histórico curto" in chosen.dropped["NEW/USDT"]
    assert "volume médio" in chosen.dropped["THIN/USDT"]


def test_universe_extra_coin_limit() -> None:
    rules = UniverseRules(recommended=("BTC/USDT", "ETH/USDT"), max_extra=1)
    chosen = select_universe(CANDIDATES, _universe_candles(), rules)
    assert chosen.kept == ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    assert "limite de 1" in chosen.dropped["ADA/USDT"]


def test_recommended_coin_without_data_is_kept_not_dropped() -> None:
    rules = UniverseRules(recommended=("BTC/USDT", "ETH/USDT"))
    only_btc = make_candles({"BTC/USDT": ramp(10, 20, 400)})
    assert select_universe({"BTC/USDT": "bitcoin", "ETH/USDT": "ethereum"}, only_btc, rules).kept == ("BTC/USDT", "ETH/USDT")


def test_recommended_must_be_valid_config() -> None:
    candles = make_candles({"BTC/USDT": ramp(10, 20, 400)})
    with pytest.raises(ValueError, match="fora do UNIVERSE"):
        select_universe({"BTC/USDT": "bitcoin"}, candles, UniverseRules(recommended=("BTC/USDT", "ETH/USDT")))
    with pytest.raises(ValueError, match="excluída"):
        select_universe({"USDC/USDT": "usd-coin"}, candles, UniverseRules(recommended=("USDC/USDT",)))
