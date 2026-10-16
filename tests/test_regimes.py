"""Regimes de mercado (Fase 4): causalidade, candles abertos, histórico curto, dados ausentes ou inválidos, transições,
reprodutibilidade, ajuste só com o passado, avaliação, integração com o pipeline e contrato com o frontend. Sem rede."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src import pipeline
from src.config import UNIVERSE
from src.loaders.market_store import write_ohlcv
from src.transformers.regime_evaluation import (
    agreement,
    episodes,
    fit_vol_threshold,
    flips_per_year,
    forward_outcomes,
    is_available,
    sensitivity,
    summarize,
    transition_counts,
    validity,
    walk_forward_vol,
    yearly_profile,
)
from src.transformers.regimes import (
    CLASSIFIER_VERSION,
    REGIME_SCHEMA,
    STATUS_INCOMPLETE,
    STATUS_INVALID,
    STATUS_NO_CANDLE,
    STATUS_OK,
    STATUS_SHORT_HISTORY,
    STATUSES,
    TREND_DOWN,
    TREND_REGIMES,
    TREND_UNDETERMINED,
    TREND_UP,
    UNAVAILABLE,
    VOL_HIGH,
    VOL_NORMAL,
    VOL_REGIMES,
    RegimeRules,
    classify_market_regimes,
    confirm_trend,
    empty_regimes,
    last_closed_day,
)
from src.transformers.selection import REGIME_DEFENSIVE, REGIME_FAVORABLE, REGIME_NEUTRAL, REGIME_UNAVAILABLE
from tests.helpers import make_candles, ramp

ROOT = Path(__file__).resolve().parent.parent
AS_OF = pd.Timestamp("2026-06-01 00:10", tz="UTC")
RULES = RegimeRules()
ONE_DAY = pd.Timedelta(days=1)


def path(days: int = 1000, seed: int = 7) -> pd.Series:
    """BTC sintético: 300 dias de alta, 250 de queda, 200 de lado, 250 de alta; picos de volatilidade no dia 600."""
    rng = np.random.default_rng(seed)
    drift = np.concatenate([np.full(300, 0.0030), np.full(250, -0.0040), np.full(200, 0.0), np.full(250, 0.0030)])[:days]
    vol = np.concatenate([np.full(600, 0.012), np.full(40, 0.06), np.full(360, 0.012)])[:days]
    close = 100.0 * np.exp(np.cumsum(drift + vol * rng.standard_normal(days)))
    return pd.Series(close, index=pd.date_range(end=last_closed_day(AS_OF), periods=days, freq="D", tz="UTC"))


def classify(close: pd.Series, as_of: pd.Timestamp = AS_OF, rules: RegimeRules = RULES) -> pd.DataFrame:
    return classify_market_regimes(close, as_of, rules)


def as_of_after(day: pd.Timestamp) -> pd.Timestamp:
    """Instante logo depois do fechamento do candle de `day`."""
    return day + ONE_DAY + pd.Timedelta(minutes=10)


# ---------------------------------------------------------------------------------------------
# 1–2. Causalidade (sem look-ahead): o futuro não muda o passado
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("k", [260, 400, 650, 900])
def test_truncating_the_future_does_not_change_any_past_row(k: int) -> None:
    close = path()
    full = classify(close)
    cut = close.iloc[: k + 1]
    truncated = classify(cut, as_of_after(cut.index[-1]))
    pd.testing.assert_frame_equal(full.iloc[: k + 1].reset_index(drop=True), truncated)


def test_changing_or_deleting_future_prices_does_not_change_past_regimes() -> None:
    close = path()
    k = 700
    base = classify(close)
    altered = close.copy()
    altered.iloc[k + 1:] = altered.iloc[k + 1:] * 9.7   # preço futuro muito diferente
    altered.iloc[k + 20] = np.nan                        # e um buraco
    altered = altered.drop(altered.index[k + 40])
    other = classify(altered)
    pd.testing.assert_frame_equal(base.iloc[: k + 1], other.iloc[: k + 1])
    assert not base.iloc[k + 1:]["close"].equals(other.iloc[k + 1:]["close"])  # o futuro mudou de fato


def test_known_at_is_the_candle_close_and_never_after_as_of() -> None:
    table = classify(path())
    assert (table["known_at"] == table["timestamp"] + ONE_DAY).all()
    assert table["known_at"].max() <= AS_OF


# ---------------------------------------------------------------------------------------------
# 3. Candles não fechados
# ---------------------------------------------------------------------------------------------

def test_open_and_future_candles_are_ignored() -> None:
    close = path()
    last = close.index[-1]
    reference = classify(close, as_of_after(last))
    open_candle = pd.concat([close, pd.Series([close.iloc[-1] * 1.5], index=[last + ONE_DAY])])
    future = pd.concat([open_candle, pd.Series([1e9], index=[last + 5 * ONE_DAY])])
    # as_of no meio do dia seguinte: o candle de last+1 ainda está aberto
    midday = last + ONE_DAY + pd.Timedelta(hours=12)
    pd.testing.assert_frame_equal(classify(future, midday), classify(close, midday))
    assert classify(future, midday)["timestamp"].iloc[-1] == last
    pd.testing.assert_frame_equal(classify(future, as_of_after(last)), reference)


def test_a_candle_is_usable_only_after_it_closes() -> None:
    day = pd.Timestamp("2026-03-10", tz="UTC")
    close = path().loc[:day]
    just_before = day + ONE_DAY - pd.Timedelta(seconds=1)
    assert classify(close, just_before)["timestamp"].iloc[-1] == day - ONE_DAY  # D ainda aberto
    assert classify(close, day + ONE_DAY)["timestamp"].iloc[-1] == day         # fechou exatamente à meia-noite


# ---------------------------------------------------------------------------------------------
# 4. Histórico insuficiente
# ---------------------------------------------------------------------------------------------

def test_short_history_is_unavailable_never_a_regime() -> None:
    table = classify(path().iloc[-150:])
    assert len(table) == 150
    assert table["status"].eq(STATUS_SHORT_HISTORY).all()
    assert table["trend_regime"].eq(UNAVAILABLE).all() and table["vol_regime"].eq(UNAVAILABLE).all()
    assert table[["dist_ma_pct", "slope_ma_pct", "trend_raw"]].isna().all().all()


def test_warmup_is_explicit_and_exact() -> None:
    table = classify(path())
    warm = RULES.trend_warmup_days
    assert table["status"].iloc[:warm].eq(STATUS_SHORT_HISTORY).all()
    assert table["status"].iloc[warm] == STATUS_OK
    # primeiro dia válido -> INDETERMINADO até `confirm_days` sinais iguais seguidos
    assert table["trend_regime"].iloc[warm: warm + RULES.confirm_days - 1].eq(TREND_UNDETERMINED).all()
    assert table["trend_regime"].iloc[warm + RULES.confirm_days - 1] in (TREND_UP, TREND_DOWN, "LATERAL", "MISTO")
    first_vol = table.index[table["vol_regime"].ne(UNAVAILABLE)][0]
    assert first_vol == RULES.vol_window + RULES.vol_min_history


def test_empty_input_and_naive_or_misaligned_index_are_handled_explicitly() -> None:
    assert classify(pd.Series(dtype="float64", index=pd.DatetimeIndex([], tz="UTC"))).empty
    assert list(empty_regimes().columns) == list(REGIME_SCHEMA)
    with pytest.raises(ValueError, match="fuso"):
        classify(pd.Series([1.0, 2.0], index=pd.date_range("2026-01-01", periods=2)))
    with pytest.raises(ValueError, match="00:00 UTC"):
        classify(pd.Series([1.0, 2.0], index=pd.date_range("2026-01-01 06:00", periods=2, freq="D", tz="UTC")))
    with pytest.raises(ValueError, match="as_of"):
        classify_market_regimes(path(), pd.Timestamp("2026-06-01"))


# ---------------------------------------------------------------------------------------------
# 5. Candles ausentes e dados inválidos
# ---------------------------------------------------------------------------------------------

def test_missing_candle_is_flagged_not_filled_and_resets_the_state() -> None:
    close = path()
    gap = close.index[500]
    table = classify(close.drop(gap))
    assert len(table) == len(close)  # o calendário continua contínuo
    row = table[table["timestamp"].eq(gap)].iloc[0]
    assert row["status"] == STATUS_NO_CANDLE and row["trend_regime"] == UNAVAILABLE and pd.isna(row["close"])
    after = table.iloc[501: 501 + RULES.confirm_days - 1]
    assert after["status"].eq(STATUS_OK).all()                       # a janela tolera um buraco...
    assert after["trend_regime"].eq(TREND_UNDETERMINED).all()        # ...mas não herda o estado de antes dele
    assert table["trend_regime"].iloc[501 + RULES.confirm_days - 1] != TREND_UNDETERMINED


def test_invalid_prices_are_marked_invalid_and_not_used() -> None:
    close = path()
    dirty = close.copy()
    dirty.iloc[500], dirty.iloc[501], dirty.iloc[502], dirty.iloc[503] = 0.0, -3.0, np.inf, np.nan
    table = classify(dirty)
    bad = table.iloc[500:504]
    assert bad["status"].eq(STATUS_INVALID).all() and bad["trend_regime"].eq(UNAVAILABLE).all()
    assert bad["close"].isna().all() and bad["dist_ma_pct"].isna().all()
    assert table["status"].iloc[504] == STATUS_OK
    assert np.isfinite(table[["dist_ma_pct", "slope_ma_pct"]].iloc[504:].to_numpy(dtype="float64")).all()


def test_long_gap_makes_windows_incomplete_until_coverage_recovers() -> None:
    close = path()
    table = classify(close.drop(close.index[400:441]))
    assert table["status"].iloc[450] == STATUS_INCOMPLETE
    assert table["trend_regime"].iloc[450] == UNAVAILABLE and pd.isna(table["dist_ma_pct"].iloc[450])
    assert table["status"].iloc[800] == STATUS_OK
    assert table["status"].isin(STATUSES).all()


def test_duplicates_keep_the_last_and_input_order_does_not_matter() -> None:
    close = path()
    shuffled = close.sample(frac=1.0, random_state=3)
    repeated = pd.concat([shuffled, close.iloc[[10, 20]] * 3.0])  # duplicados antigos primeiro
    repeated = pd.concat([repeated.iloc[-2:], shuffled])         # ...e os valores válidos depois: valem estes
    pd.testing.assert_frame_equal(classify(repeated), classify(close))


# ---------------------------------------------------------------------------------------------
# 6. Transições
# ---------------------------------------------------------------------------------------------

def test_confirmation_delays_a_new_state_by_confirm_days_and_ignores_short_blips() -> None:
    n = 5
    out = confirm_trend(["ALTA"] * 3 + ["BAIXA"] * 2 + ["ALTA"] * 10, n)
    assert out == [TREND_UNDETERMINED] * 9 + [TREND_UP] * 6  # o 5º ALTA seguido (posição 9) confirma
    steady = ["ALTA"] * 6 + ["BAIXA"] * 4 + ["ALTA"] * 3  # blip de 4 dias < 5: o estado não troca
    assert confirm_trend(steady, n)[-1] == TREND_UP
    switch = ["ALTA"] * 6 + ["BAIXA"] * 5
    assert confirm_trend(switch, n)[-5:] == [TREND_UP] * 4 + [TREND_DOWN]
    assert confirm_trend(["ALTA", "ALTA", None, "ALTA"], 2) == [TREND_UNDETERMINED, TREND_UP, UNAVAILABLE, TREND_UNDETERMINED]
    assert confirm_trend(["ALTA", "BAIXA"], 1) == [TREND_UP, TREND_DOWN]


def test_trend_follows_the_synthetic_cycle_and_volatility_spike_is_flagged() -> None:
    table = classify(path())
    trend = table["trend_regime"]
    assert {TREND_UP, TREND_DOWN} <= set(trend)
    assert trend[trend.eq(TREND_UP)].index[0] < trend[trend.eq(TREND_DOWN)].index[0]  # a alta vem antes da queda
    assert set(table["vol_regime"]) <= set(VOL_REGIMES) and set(trend) <= set(TREND_REGIMES)
    # ALTA é relativa ao passado do próprio ativo (percentil): com ruído estacionário ~20% dos dias seriam ALTA por
    # construção; o pico de volatilidade, porém, tem de estar entre os dias ALTA, no topo da distribuição.
    assert table["vol_regime"].iloc[625:640].eq(VOL_HIGH).all()
    assert table["vol_rank_pct"].iloc[625:640].min() > 95.0
    assert table["vol_regime"].iloc[RULES.vol_window + RULES.vol_min_history:].eq(VOL_NORMAL).any()


def test_raw_signal_rules() -> None:
    # preço bem acima de média subindo -> ALTA; bem abaixo de média caindo -> BAIXA
    up = classify(pd.Series(ramp(100, 400, 400), index=pd.date_range(end=last_closed_day(AS_OF), periods=400, freq="D", tz="UTC")))
    assert up["trend_raw"].iloc[-1] == TREND_UP and up["trend_regime"].iloc[-1] == TREND_UP
    down = classify(pd.Series(ramp(400, 100, 400), index=pd.date_range(end=last_closed_day(AS_OF), periods=400, freq="D", tz="UTC")))
    assert down["trend_raw"].iloc[-1] == TREND_DOWN
    flat = classify(pd.Series(np.full(400, 100.0), index=pd.date_range(end=last_closed_day(AS_OF), periods=400, freq="D", tz="UTC")))
    assert flat["trend_raw"].iloc[-1] == "LATERAL"


# ---------------------------------------------------------------------------------------------
# 7. Estabilidade e reprodutibilidade
# ---------------------------------------------------------------------------------------------

def test_same_data_and_parameters_reproduce_the_same_table_and_fingerprints() -> None:
    close = path()
    a, b = classify(close), classify(close.copy())
    pd.testing.assert_frame_equal(a, b)
    assert a["classifier_version"].eq(CLASSIFIER_VERSION).all()
    assert a["params_hash"].nunique() == 1 and a["data_fingerprint"].is_unique
    assert list(a.columns) == list(REGIME_SCHEMA) and {c: str(t) for c, t in a.dtypes.items()}.keys() == REGIME_SCHEMA.keys()


def test_any_change_in_parameters_or_data_changes_the_fingerprints() -> None:
    close = path()
    base = classify(close)
    other_rules = classify(close, rules=replace(RULES, trend_band=0.06))
    assert other_rules["params_hash"].iloc[0] != base["params_hash"].iloc[0]
    changed = close.copy()
    changed.iloc[300] *= 1.01
    moved = classify(changed)
    assert moved["data_fingerprint"].iloc[299] == base["data_fingerprint"].iloc[299]  # antes da mudança: igual
    assert (moved["data_fingerprint"].iloc[300:] != base["data_fingerprint"].iloc[300:]).all()  # depois: diferente


def test_confirmation_reduces_flips_compared_with_the_raw_signal() -> None:
    close = path(seed=11)
    raw_like = classify(close, rules=replace(RULES, confirm_days=1))
    smoothed = classify(close)
    assert flips_per_year(smoothed, "trend_regime").sum() < flips_per_year(raw_like, "trend_regime").sum()
    pd.testing.assert_series_equal(raw_like["trend_raw"].dropna().reset_index(drop=True),
                                   raw_like["trend_regime"][raw_like["trend_raw"].notna()].reset_index(drop=True), check_names=False)


def test_invalid_rules_are_rejected() -> None:
    for bad in (dict(confirm_days=0), dict(vol_exit=0.9, vol_enter=0.8), dict(min_coverage=0.0), dict(trend_band=-1.0), dict(ma_window=1)):
        with pytest.raises(ValueError):
            RegimeRules(**bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# 8–9. Parâmetros ajustados só com o passado; nada retrospectivo na classificação operacional
# ---------------------------------------------------------------------------------------------

def test_volatility_rank_uses_only_strictly_earlier_observations() -> None:
    table = classify(path())
    vol = table["vol_ann_pct"].to_numpy(dtype="float64")
    rank = table["vol_rank_pct"].to_numpy(dtype="float64")
    shown = np.isfinite(vol)
    for i in np.flatnonzero(np.isfinite(rank))[::40]:
        past = vol[:i][shown[:i]]
        expected = ((past < vol[i]).sum() + 0.5 * (past == vol[i]).sum()) / len(past)
        assert rank[i] == pytest.approx(expected * 100.0)
        assert len(past) >= RULES.vol_min_history


def test_fitted_threshold_never_sees_data_at_or_after_the_train_end() -> None:
    idx = pd.date_range("2024-01-01", periods=800, freq="D", tz="UTC")
    vol = pd.Series(np.random.default_rng(1).uniform(20, 80, 800), index=idx)
    end = pd.Timestamp("2025-06-01", tz="UTC")
    base = fit_vol_threshold(vol, end, 0.8)
    mutated = vol.copy()
    mutated[mutated.index >= end] = 1e6
    assert fit_vol_threshold(mutated, end, 0.8) == base
    mutated_before = vol.copy()
    mutated_before[mutated_before.index < end] += 5.0
    assert fit_vol_threshold(mutated_before, end, 0.8) != base  # e usa, sim, os dados anteriores
    assert np.isnan(fit_vol_threshold(vol, idx[0], 0.8))


def test_walk_forward_threshold_for_a_year_ignores_that_year_and_later() -> None:
    close = path()
    table = classify(close)
    wf = walk_forward_vol(table, RULES.vol_enter, RULES.vol_min_history)
    assert not wf.empty and wf["test_year"].is_monotonic_increasing
    year = int(wf["test_year"].iloc[-1])
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    mutated = close.copy()
    mutated[mutated.index > start] *= 3.3
    wf2 = walk_forward_vol(classify(mutated), RULES.vol_enter, RULES.vol_min_history)
    pd.testing.assert_series_equal(wf.set_index("test_year")["threshold_vol_pct"], wf2.set_index("test_year")["threshold_vol_pct"])


def test_operational_labels_are_filtered_not_smoothed_only_the_evaluation_looks_ahead() -> None:
    close = path()
    k = 600
    altered = close.copy()
    altered.iloc[k + 1:] *= 0.2
    a, b = classify(close), classify(altered)
    pd.testing.assert_frame_equal(a.iloc[: k + 1], b.iloc[: k + 1])     # classificação: não vê o futuro
    fa, fb = forward_outcomes(a), forward_outcomes(b)
    assert not fa["fwd_ret_mean_pct"].equals(fb["fwd_ret_mean_pct"])    # o desfecho posterior, sim, depende dele


# ---------------------------------------------------------------------------------------------
# Avaliação: episódios, transições, amostra insuficiente
# ---------------------------------------------------------------------------------------------

def table_of(trend: list[str], vol: list[str] | None = None) -> pd.DataFrame:
    n = len(trend)
    ts = pd.date_range("2024-12-29", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "trend_regime": trend, "vol_regime": vol or [VOL_NORMAL] * n,
        "close": np.linspace(100.0, 120.0, n), "vol_ann_pct": np.full(n, 40.0), "status": STATUS_OK, "vol_status": STATUS_OK,
    })


def test_episodes_summary_transitions_and_flips() -> None:
    t = table_of(["ALTA", "ALTA", "ALTA", "BAIXA", "BAIXA", "INDISPONIVEL", "ALTA", "INDETERMINADO", "ALTA"])
    eps = episodes(t, "trend_regime")
    assert eps[["label", "days"]].values.tolist() == [["ALTA", 3], ["BAIXA", 2], ["ALTA", 1], ["ALTA", 1]]
    s = summarize(t, "trend_regime").set_index("label")
    assert s.loc["ALTA", "days"] == 5 and s.loc["ALTA", "episodes"] == 3 and s.loc["BAIXA", "episodes"] == 1
    assert s["share_pct"].sum() == pytest.approx(100.0)
    tc = transition_counts(t, "trend_regime")
    assert tc.values.tolist() == [["ALTA", "BAIXA", 1]]  # saltos sobre buracos não contam
    assert flips_per_year(t, "trend_regime").to_dict() == {2024: 0, 2025: 1}


def test_agreement_sensitivity_validity_and_profile() -> None:
    close = path()
    base = classify(close)
    variants = {"banda +20%": replace(RULES, trend_band=0.06), "confirmação 3": replace(RULES, confirm_days=3)}
    sens = sensitivity(close, AS_OF, RULES, variants)
    assert sens["variant"].tolist() == ["base", "banda +20%", "confirmação 3"]
    assert sens.loc[0, "trend_agreement_pct"] == 100.0 and sens.loc[0, "vol_agreement_pct"] == 100.0
    assert agreement(pd.Series(["a", "b", None]), pd.Series(["a", "c", "a"])) == 0.5
    v = validity(base).set_index(["dimension", "status"])["days"]
    assert v[("trend", STATUS_SHORT_HISTORY)] == RULES.trend_warmup_days and v[("trend", STATUS_OK)] == len(base) - RULES.trend_warmup_days
    prof = yearly_profile(base)
    assert prof["days"].sum() == len(base) and prof["year"].is_monotonic_increasing


def test_forward_outcomes_flag_small_samples_instead_of_concluding() -> None:
    t = table_of(["ALTA"] * 20 + ["BAIXA"] * 20 + ["ALTA"] * 20)
    out = forward_outcomes(t, horizon=5, min_episodes=5).set_index(["dimension", "label"])
    assert out.loc[("trend_regime", "ALTA"), "sample"] == "AMOSTRA_INSUFICIENTE"
    assert out.loc[("trend_regime", "ALTA"), "episodes"] == 2
    assert is_available(table_of(["ALTA"])) and not is_available(table_of(["INDISPONIVEL"]))
    assert not is_available(empty_regimes())


# ---------------------------------------------------------------------------------------------
# 10–12. Integração com o pipeline, consumidores existentes, dados externos indisponíveis
# ---------------------------------------------------------------------------------------------

@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _base() -> pd.DataFrame:
    yesterday = pd.Timestamp.now(tz="UTC").floor("D") - ONE_DAY
    symbols = [s for s in UNIVERSE if s in ("BTC/USDT", "ETH/USDT", "SOL/USDT")]
    return make_candles({s: ramp(50, 150, 420) for s in symbols}, yesterday)  # sem Fear & Greed nem CoinGecko


TRADING = ["symbol", "opportunity", "score", "selected", "candidate_rank", "target_fraction", "allocation_brl"]


def test_pipeline_publishes_regimes_without_fear_greed_and_leaves_trading_untouched(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_ohlcv(_base())
    result = pipeline.analyze(pd.Timestamp.now(tz="UTC"))
    published = pd.read_parquet(workdir / "frontend" / "public" / "market_regimes.parquet")
    assert list(published.columns) == list(REGIME_SCHEMA)
    last = result["market_regimes"].iloc[-1]
    assert last["status"] == STATUS_OK  # sem Fear & Greed nem CoinGecko na base, o regime continua classificado
    assert last["trend_regime"] == TREND_UP and is_available(result["market_regimes"])
    rec = result["recommendation"].iloc[0]
    assert rec["regime"] == last["legacy_regime"] == REGIME_FAVORABLE  # o regime antigo segue com o mesmo significado
    assert result["signals"]["fng_value"].isna().all()

    real: Callable[..., pd.DataFrame] = pipeline.classify_market_regimes

    def extreme(*args: Any, **kwargs: Any) -> pd.DataFrame:
        return real(*args, **kwargs).assign(trend_regime=TREND_DOWN, vol_regime=VOL_HIGH)

    monkeypatch.setattr(pipeline, "classify_market_regimes", extreme)
    other = pipeline.analyze(pd.Timestamp.now(tz="UTC"))
    assert other["market_regimes"]["trend_regime"].eq(TREND_DOWN).all()
    pd.testing.assert_frame_equal(result["signals"][TRADING], other["signals"][TRADING])
    pd.testing.assert_frame_equal(
        result["recommendation"][["regime", "total_brl", "decision", "n_selected"]],
        other["recommendation"][["regime", "total_brl", "decision", "n_selected"]],
    )
    pd.testing.assert_frame_equal(result["selection_backtest"], other["selection_backtest"])


def test_stale_base_shows_missing_candles_as_unavailable_regime(workdir: Path) -> None:
    write_ohlcv(_base())
    table = pipeline.analyze(pd.Timestamp.now(tz="UTC") + 10 * ONE_DAY)["market_regimes"]
    tail = table.tail(5)
    assert tail["status"].eq(STATUS_NO_CANDLE).all() and tail["trend_regime"].eq(UNAVAILABLE).all()
    assert not is_available(table)


def test_legacy_regime_values_keep_their_meaning_and_frontend_contract_matches() -> None:
    ts = (ROOT / "frontend" / "src" / "types" / "signals.ts").read_text(encoding="utf-8")
    loader = (ROOT / "frontend" / "src" / "data" / "loadSignals.ts").read_text(encoding="utf-8")

    def tuple_of(name: str) -> tuple[str, ...]:
        match = re.search(rf"export const {name} = \[(.*?)\] as const", ts, re.S)
        assert match, name
        return tuple(re.findall(r'"([^"]+)"', match.group(1)))

    assert tuple_of("REGIMES") == (REGIME_FAVORABLE, REGIME_NEUTRAL, REGIME_DEFENSIVE, REGIME_UNAVAILABLE)  # consumidores antigos
    assert tuple_of("MARKET_TREND_REGIMES") == TREND_REGIMES
    assert tuple_of("MARKET_VOL_REGIMES") == VOL_REGIMES
    assert tuple_of("REGIME_STATUSES") == STATUSES
    body = re.search(r"export interface MarketRegime \{(.*?)\n\}", ts, re.S)
    assert body
    assert re.findall(r"readonly (\w+):", body.group(1)) == list(REGIME_SCHEMA)
    parser = re.search(r"const parseMarketRegime = .*?\n\}\);", loader, re.S)
    assert parser
    assert re.findall(r'r, "(\w+)"', parser.group(0)) == list(REGIME_SCHEMA)
    assert "market_regimes.parquet" in loader and "optionalRows(`${base}/market_regimes.parquet`)" in loader  # arquivo opcional
