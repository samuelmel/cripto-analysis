"""IA em modo sombra: boosting determinístico, previsão do dia sem olhar o futuro, registro imutável e cópia do F&G."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import pipeline
from src.loaders.market_store import write_fng, write_ohlcv
from src.loaders.model_log_store import (
    PredictionLogIntegrityError,
    append_fng_history,
    append_predictions,
    read_fng_history,
    read_predictions,
)
from src.loaders.parquet_loader import write_parquet
from src.transformers.data_quality import clean_candles
from src.transformers.entry_model import PURGE_DAYS, model_features, outperform_target
from src.transformers.entry_signals import EntryRules, build_panel
from src.transformers.gbm import GBMParams, fit_gbm, predict_gbm
from src.transformers.model_shadow import (
    MODELS,
    latest_fng,
    live_predictions,
    new_fng_rows,
    realized_outcomes,
    stack_all,
    verify_chain,
    walk_forward,
)
from tests.synthetic_market import RUN_TS, synthetic_candles, synthetic_fng

UTC = "UTC"


def _rows(candles: pd.DataFrame, fng: pd.DataFrame | None) -> tuple[pd.DataFrame, object]:
    panel = build_panel(candles, EntryRules())
    series = fng.set_index("timestamp")["fng_value"].astype("float64") if fng is not None else None
    return stack_all(model_features(panel, series), outperform_target(panel, "BTC/USDT"), panel.member), panel


@pytest.fixture(scope="module")
def market() -> dict[str, object]:
    candles = clean_candles(synthetic_candles())
    fng = synthetic_fng(candles)
    rows, panel = _rows(candles, fng)
    return {"candles": candles, "fng": fng, "rows": rows, "panel": panel}


# ------------------------------------------------------------------------------ boosting

def test_gbm_is_deterministic_and_learns_an_interaction_the_linear_model_cannot() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(size=(6000, 3))
    y = (rng.random(6000) < np.where(x[:, 0] * x[:, 1] > 0, 0.8, 0.2)).astype(float)
    p = GBMParams(n_rounds=60, min_leaf=50)
    a, b = fit_gbm(x, y, p), fit_gbm(x, y, p)
    xt = rng.normal(size=(3000, 3))
    assert np.array_equal(predict_gbm(a, xt), predict_gbm(b, xt))
    truth = np.where(xt[:, 0] * xt[:, 1] > 0, 1.0, 0.0)
    assert ((predict_gbm(a, xt) > 0.5) == truth.astype(bool)).mean() > 0.85
    with pytest.raises(ValueError):
        fit_gbm(np.array([[np.nan]]), np.array([1.0]))


def test_gbm_bins_come_only_from_the_training_rows() -> None:
    rng = np.random.default_rng(2)
    x = rng.normal(size=(2000, 2))
    y = (x[:, 0] > 0).astype(float)
    m = fit_gbm(x, y, GBMParams(n_rounds=10, min_leaf=50))
    huge = np.array([[1e9, 0.0], [-1e9, 0.0]])
    assert np.isfinite(predict_gbm(m, huge)).all()  # valores fora da faixa do treino caem nas faixas extremas


# ------------------------------------------------------------------------------ previsão do dia

def test_live_training_targets_end_before_the_prediction_day(market: dict[str, object]) -> None:
    rows = market["rows"]
    assert isinstance(rows, pd.DataFrame)
    day = pd.Timestamp("2026-03-01", tz=UTC)
    preds, notes = live_predictions(rows, day, run_ts=RUN_TS, data_fingerprint="fp", code_version="test")
    assert set(preds["model"]) == {m.name for m in MODELS} and not notes
    assert (preds["train_end"] == day - pd.Timedelta(days=PURGE_DAYS)).all()
    # o alvo de uma linha de treino em t olha até t+31: com t <= dia − 31, termina no próprio dia, nunca depois
    assert (preds["train_end"] + pd.Timedelta(days=1 + 30) <= day).all()
    for _, part in preds.groupby("model"):
        assert sorted(part["rank"].tolist()) == list(range(1, len(part) + 1))
        assert part["in_top_k"].sum() == min(5, len(part))


def test_prices_after_the_day_do_not_change_the_prediction(market: dict[str, object]) -> None:
    candles, fng = market["candles"], market["fng"]
    assert isinstance(candles, pd.DataFrame) and isinstance(fng, pd.DataFrame)
    day = pd.Timestamp("2025-09-15", tz=UTC)
    full, _ = _rows(candles, fng)
    cut, _ = _rows(candles[candles["timestamp"].le(day)], fng[fng["timestamp"].le(day)])
    a, _ = live_predictions(full, day, run_ts=RUN_TS, data_fingerprint="x", code_version="t")
    b, _ = live_predictions(cut, day, run_ts=RUN_TS, data_fingerprint="x", code_version="t")
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


def test_missing_fear_and_greed_skips_only_the_models_that_use_it(market: dict[str, object]) -> None:
    candles = market["candles"]
    assert isinstance(candles, pd.DataFrame)
    rows, _ = _rows(candles, None)
    day = pd.Timestamp("2026-03-01", tz=UTC)
    preds, notes = live_predictions(rows, day, run_ts=RUN_TS, data_fingerprint="fp", code_version="t")
    assert set(preds["model"]) == {"F_LOGIT_SEM_FNG", "G_GBM_SEM_FNG"}
    assert len(notes) == 2 and all("Fear & Greed ausente" in n for n in notes)  # ausência não vira zero


def test_walk_forward_trains_only_before_each_year(market: dict[str, object]) -> None:
    rows = market["rows"]
    assert isinstance(rows, pd.DataFrame)
    spec = next(m for m in MODELS if m.name == "F_LOGIT_SEM_FNG")
    prob, folds = walk_forward(spec, rows, (2022, 2023))
    assert list(folds["year"]) == [2022, 2023]
    assert (folds["train_end"] == pd.to_datetime(["2021-12-31", "2022-12-31"], utc=True) - pd.Timedelta(days=PURGE_DAYS)).all()
    years = pd.DatetimeIndex(prob.index.get_level_values("timestamp")).year
    assert set(years) == {2022, 2023} and prob.between(0, 1).all()


def test_realized_outcomes_only_for_mature_predictions(market: dict[str, object]) -> None:
    rows, panel = market["rows"], market["panel"]
    assert isinstance(rows, pd.DataFrame)
    last = pd.DatetimeIndex(rows.index.get_level_values("timestamp")).max()
    old, _ = live_predictions(rows, last - pd.Timedelta(days=60), run_ts=RUN_TS, data_fingerprint="f", code_version="t")
    new, _ = live_predictions(rows, last - pd.Timedelta(days=5), run_ts=RUN_TS, data_fingerprint="f", code_version="t")
    out = realized_outcomes(pd.concat([old, new], ignore_index=True), panel)  # type: ignore[arg-type]
    assert set(out["day"]) == {last - pd.Timedelta(days=60)}       # a de 5 dias atrás ainda não terminou
    assert out["target"].isin([0.0, 1.0]).all()


# ------------------------------------------------------------------------------ registro e F&G

def test_prediction_log_is_append_only_and_detects_tampering(market: dict[str, object], tmp_path: Path) -> None:
    rows = market["rows"]
    assert isinstance(rows, pd.DataFrame)
    path = tmp_path / "model_predictions.parquet"
    day = pd.Timestamp("2026-03-01", tz=UTC)
    preds, _ = live_predictions(rows, day, run_ts=RUN_TS, data_fingerprint="fp", code_version="t")
    assert append_predictions(preds, path) == len(preds)
    assert append_predictions(preds, path) == 0                    # o mesmo dia não é regravado
    log = read_predictions(path)
    assert verify_chain(log) == []
    tampered = log.copy()
    tampered.loc[0, "prob"] = 0.99
    write_parquet(tampered, path)
    with pytest.raises(PredictionLogIntegrityError):
        append_predictions(preds, path)


def test_fng_history_keeps_revisions_and_reads_the_latest(tmp_path: Path) -> None:
    path = tmp_path / "fng_history.parquet"
    day = pd.Timestamp("2026-10-01", tz=UTC)
    first = pd.DataFrame({"timestamp": [day, day + pd.Timedelta(days=1)], "symbol": "MARKET", "fng_value": [30, 40],
                          "fng_classification": ["Fear", "Fear"]})
    assert append_fng_history(first, pd.Timestamp("2026-10-02 21:00", tz=UTC), path) == 2
    assert append_fng_history(first, pd.Timestamp("2026-10-03 21:00", tz=UTC), path) == 0     # idempotente
    revised = first.assign(fng_value=[30, 45])
    assert append_fng_history(revised, pd.Timestamp("2026-10-04 21:00", tz=UTC), path) == 1   # revisão auditável
    history = read_fng_history(path)
    assert len(history) == 3
    latest = latest_fng(history).set_index("timestamp")
    assert int(latest.loc[day + pd.Timedelta(days=1), "fng_value"]) == 45
    assert new_fng_rows(history, pd.DataFrame(), RUN_TS).empty


def test_pipeline_records_shadow_predictions_and_fng_only_with_record_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    candles = synthetic_candles()
    write_ohlcv(candles)
    write_fng(synthetic_fng(candles))
    result = pipeline.analyze(RUN_TS)
    assert not result["shadow_predictions"].empty                  # calculado sempre, gravado só com --record-state
    assert not (tmp_path / "data" / "state" / "model_predictions.parquet").exists()
    assert "IA em sombra" in pipeline.report(result)
    pipeline.analyze(RUN_TS, record_state=True)
    log = read_predictions(tmp_path / "data" / "state" / "model_predictions.parquet")
    assert set(log["model"]) == {m.name for m in MODELS} and verify_chain(log) == []
    assert len(read_fng_history(tmp_path / "data" / "state" / "fng_history.parquet")) > 1000
    # recomendação e sinais não dependem dos modelos em sombra
    assert "prob" not in result["signals"].columns


def test_pipeline_uses_the_saved_fng_copy_when_the_source_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    candles = synthetic_candles()
    write_ohlcv(candles)
    fng = synthetic_fng(candles)
    append_fng_history(fng, RUN_TS, tmp_path / "data" / "state" / "fng_history.parquet")
    result = pipeline.analyze(RUN_TS)                              # data/market sem F&G: a fonte "falhou"
    assert set(result["shadow_predictions"]["model"]) >= {"F_LOGIT", "G_GBM"}
