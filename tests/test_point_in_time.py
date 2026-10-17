"""Universo point-in-time: sem dado futuro, truncagem invariante, deslistagem, episódios e volume medido em D."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.point_in_time import (
    EVENT_FIRST,
    EVENT_GAP,
    EVENT_LAST,
    REASON_ELIGIBLE,
    REASON_EXCLUDED,
    REASON_LEVERAGED,
    REASON_LOW_VOLUME,
    REASON_NOT_TRADING,
    REASON_OUTSIDE_LIMIT,
    REASON_SHORT_HISTORY,
    PointInTimeRules,
    assign_episodes,
    listing_events,
    review_flags,
    survivorship_summary,
    universe_history,
    universe_on,
)

RULES = PointInTimeRules(
    min_history_days=30, min_avg_volume_usd=1_000.0, volume_window_days=10, max_stale_days=1,
    episode_gap_days=7, max_size=3, always_include=("BTC/USDT",), excluded={"USDC": "stablecoin"},
)
WIDE = PointInTimeRules(
    min_history_days=30, min_avg_volume_usd=1_000.0, volume_window_days=10, max_stale_days=1,
    episode_gap_days=7, max_size=50, always_include=("BTC/USDT",), excluded={"USDC": "stablecoin"},
)  # sem limite de tamanho efetivo: isola os outros filtros


def _series(symbol: str, start: str, end: str, volume: float | list[float] = 5_000.0, price: float = 10.0) -> pd.DataFrame:
    days = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq="D")
    vol = np.full(len(days), volume, dtype="float64") if isinstance(volume, float) else np.asarray(volume, dtype="float64")
    return pd.DataFrame({"symbol": symbol, "timestamp": days, "close": price, "quote_volume": vol})


def _market() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    frames = [
        _series("BTC/USDT", "2020-01-01", "2020-12-31", 9_000.0),
        _series("AAA/USDT", "2020-01-01", "2020-12-31", 8_000.0),
        _series("BBB/USDT", "2020-01-01", "2020-06-30", 7_000.0),   # deslistada em 30/06
        _series("CCC/USDT", "2020-03-01", "2020-12-31", 6_000.0),   # listada depois
        _series("DDD/USDT", "2020-01-01", "2020-12-31", list(rng.uniform(4_000, 12_000, 366))),
        _series("USDC/USDT", "2020-01-01", "2020-12-31", 50_000.0),
        _series("BTCUP/USDT", "2020-01-01", "2020-12-31", 50_000.0),
    ]
    # Volume que só cresce depois: na metade do ano a EEE ainda é ilíquida.
    late = _series("EEE/USDT", "2020-01-01", "2020-12-31", [100.0] * 183 + [20_000.0] * 183)
    return pd.concat([*frames, late], ignore_index=True)


def _day(history: pd.DataFrame, day: str) -> pd.DataFrame:
    return history[history["timestamp"].eq(pd.Timestamp(day, tz="UTC"))].set_index("symbol")


@pytest.mark.parametrize("cut", ["2020-02-15", "2020-05-20", "2020-06-30", "2020-07-02", "2020-09-01"])
def test_truncating_after_d_does_not_change_the_universe_up_to_d(cut: str) -> None:
    candles = _market()
    d = pd.Timestamp(cut, tz="UTC")
    full = universe_history(candles, RULES)
    truncated = universe_history(candles[candles["timestamp"].le(d)], RULES)
    left = full[full["timestamp"].le(d)].sort_values(["timestamp", "symbol"], ignore_index=True)
    right = truncated.sort_values(["timestamp", "symbol"], ignore_index=True)
    pd.testing.assert_frame_equal(left, right)


def test_future_prices_and_volumes_do_not_influence_past_eligibility() -> None:
    candles = _market()
    d = pd.Timestamp("2020-06-15", tz="UTC")
    tampered = candles.copy()
    after = tampered["timestamp"].gt(d)
    tampered.loc[after, "quote_volume"] *= 1_000.0
    tampered.loc[after, "close"] *= 50.0
    a = universe_history(candles, RULES)
    b = universe_history(tampered, RULES)
    pd.testing.assert_frame_equal(a[a["timestamp"].le(d)].reset_index(drop=True), b[b["timestamp"].le(d)].reset_index(drop=True))


def test_delisted_pair_stays_in_history_until_its_last_candle_then_stops_trading() -> None:
    history = universe_history(_market(), WIDE)
    bbb = history[history["symbol"].eq("BBB/USDT")].set_index("timestamp")
    assert bbb.loc[pd.Timestamp("2020-06-30", tz="UTC"), "days_since_candle"] == 0
    assert bbb.loc[pd.Timestamp("2020-07-01", tz="UTC"), "reason"] != REASON_NOT_TRADING  # tolerância de 1 dia
    assert bbb.loc[pd.Timestamp("2020-07-02", tz="UTC"), "reason"] == REASON_NOT_TRADING
    assert not bbb.loc[pd.Timestamp("2020-07-02", tz="UTC"):, "eligible"].any()
    assert bbb.loc[pd.Timestamp("2020-05-01", tz="UTC"), "eligible"]  # era elegível antes de sair


def test_listing_events_mark_last_candle_as_inferred_delisting() -> None:
    events = listing_events(_market(), pd.Timestamp("2021-01-02 00:10", tz="UTC"), RULES)
    last = events[events["event"].eq(EVENT_LAST)]
    assert last["symbol"].tolist() == ["BBB/USDT"]
    assert last["inferred"].all()
    assert last["timestamp"].iloc[0] == pd.Timestamp("2020-06-30", tz="UTC")
    assert set(events.loc[events["event"].eq(EVENT_FIRST), "symbol"]) == set(_market()["symbol"])


def test_listed_later_has_no_rows_before_listing_and_needs_its_own_history() -> None:
    history = universe_history(_market(), WIDE)
    ccc = history[history["symbol"].eq("CCC/USDT")]
    assert ccc["timestamp"].min() == pd.Timestamp("2020-03-01", tz="UTC")
    first_ok = ccc.loc[ccc["eligible"], "timestamp"].min()
    assert first_ok >= pd.Timestamp("2020-03-30", tz="UTC")  # 30 candles próprios
    assert ccc.iloc[0]["reason"] == REASON_SHORT_HISTORY


def test_volume_is_measured_up_to_d_not_today() -> None:
    history = universe_history(_market(), RULES)
    mid = _day(history, "2020-06-01")
    late = _day(history, "2020-12-01")
    assert mid.loc["EEE/USDT", "reason"] == REASON_LOW_VOLUME
    assert late.loc["EEE/USDT", "eligible"] or late.loc["EEE/USDT", "reason"] == REASON_OUTSIDE_LIMIT


def test_exclusions_leverage_and_size_limit_with_forced_core() -> None:
    history = universe_history(_market(), RULES)
    day = _day(history, "2020-05-01")
    assert day.loc["USDC/USDT", "reason"] == REASON_EXCLUDED
    assert day.loc["BTCUP/USDT", "reason"] == REASON_LEVERAGED
    chosen = universe_on(history, pd.Timestamp("2020-05-01", tz="UTC"))
    assert len(chosen) == RULES.max_size
    assert "BTC/USDT" in chosen
    extras = day[day["eligible"] & ~day.index.isin(["BTC/USDT"])]
    outside = day[day["reason"].eq(REASON_OUTSIDE_LIMIT)]
    assert extras["avg_volume_usd"].min() >= outside["avg_volume_usd"].max()
    assert (day["reason"] == REASON_ELIGIBLE).sum() == RULES.max_size


def test_core_coins_follow_the_live_rule_and_never_leave_for_history_or_volume() -> None:
    """Como `universe.select_universe`: BTC (always_include) entra sem 30 candles próprios e com volume baixo,
    mas não entra se for excluído ou se parar de negociar."""
    candles = pd.concat([_series("BTC/USDT", "2020-01-01", "2020-03-01", 10.0),
                         _series("AAA/USDT", "2020-01-01", "2020-03-01", 9_000.0)], ignore_index=True)
    day = _day(universe_history(candles, RULES), "2020-01-05")
    assert day.loc["BTC/USDT", "eligible"] and day.loc["BTC/USDT", "reason"] == REASON_ELIGIBLE
    assert day.loc["AAA/USDT", "reason"] == REASON_SHORT_HISTORY
    stopped = _day(universe_history(candles, RULES), "2020-03-01")
    assert stopped.loc["BTC/USDT", "eligible"]
    gone = universe_history(pd.concat([candles, _series("CCC/USDT", "2020-01-01", "2020-03-20")], ignore_index=True), RULES)
    assert _day(gone, "2020-03-10").loc["BTC/USDT", "reason"] == REASON_NOT_TRADING


def test_long_gap_starts_a_new_episode_with_fresh_history() -> None:
    old = _series("LUNA/USDT", "2020-01-01", "2020-05-13", 9_000.0, price=80.0)
    new = _series("LUNA/USDT", "2020-05-31", "2020-12-31", 9_000.0, price=8.0)  # 17 dias sem candle
    candles = pd.concat([old, new, _series("BTC/USDT", "2020-01-01", "2020-12-31", 9_000.0)], ignore_index=True)
    ep = assign_episodes(candles[candles["symbol"].eq("LUNA/USDT")], RULES.episode_gap_days)
    assert ep["episode"].tolist() == [0] * len(old) + [1] * len(new)
    history = universe_history(candles, RULES).set_index(["symbol", "timestamp"])
    restart = history.loc[("LUNA/USDT", pd.Timestamp("2020-05-31", tz="UTC"))]
    assert restart["history_days"] == 1 and restart["episode"] == 1
    assert restart["reason"] == REASON_SHORT_HISTORY
    gap_day = history.loc[("LUNA/USDT", pd.Timestamp("2020-05-20", tz="UTC"))]
    assert gap_day["reason"] == REASON_NOT_TRADING
    events = listing_events(candles, pd.Timestamp("2021-01-01 00:10", tz="UTC"), RULES)
    gaps = events[events["event"].eq(EVENT_GAP)]
    assert gaps["timestamp"].tolist() == [pd.Timestamp("2020-05-13", tz="UTC")]


def test_short_gap_within_tolerance_is_the_same_episode() -> None:
    a = _series("AAA/USDT", "2020-01-01", "2020-03-01")
    b = _series("AAA/USDT", "2020-03-05", "2020-04-01")  # 3 dias sem candle: manutenção, não troca de ativo
    ep = assign_episodes(pd.concat([a, b], ignore_index=True), RULES.episode_gap_days)
    assert ep["episode"].eq(0).all()


def test_survivorship_summary_counts_pairs_absent_from_todays_list() -> None:
    history = universe_history(_market(), RULES)
    summary = survivorship_summary(history, current_universe=["BTC/USDT", "AAA/USDT"], ended={"BBB/USDT"})
    row = summary.set_index("year").loc[2020]
    assert row["distinct_eligible"] > row["in_current_universe"]
    assert row["later_ended"] == 1


def test_review_flags_only_mark_suspected_tokenized_equities() -> None:
    catalog = pd.DataFrame({"symbol": ["AAPLB/USDT", "BNB/USDT", "ARB/USDT", "TSLAB/USDT", "USDSB/USDT"],
                            "first_month": ["2025-06", "2017-11", "2023-03", "2024-01", "2025-02"]})
    rules = PointInTimeRules(excluded={"USDSB": "stablecoin"})
    flags = review_flags(catalog, rules)
    assert flags["symbol"].tolist() == ["AAPLB/USDT"]  # BNB/ARB antigos; TSLAB antes de 2025; USDSB já excluída


def test_empty_candles_give_an_empty_typed_frame() -> None:
    out = universe_history(pd.DataFrame(columns=["symbol", "timestamp", "close", "quote_volume"]).astype(
        {"timestamp": "datetime64[ns, UTC]", "close": "float64", "quote_volume": "float64"}), RULES)
    assert out.empty and "eligible" in out.columns


def test_invalid_rules_are_rejected() -> None:
    with pytest.raises(ValueError):
        PointInTimeRules(max_stale_days=7, episode_gap_days=7)
