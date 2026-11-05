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
    AI_STATUS_SCHEMA,
    GATE_APPROVED,
    GATE_BAD_CHAIN,
    GATE_FEW_DAYS,
    GATE_ID,
    GATE_MIN_DAYS,
    GATE_REJECTED,
    MODELS,
    ai_picks_today,
    ai_status_table,
    apply_ai_selection,
    chain_rows,
    daily_excess,
    promotion_gate,
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


# ------------------------------------------------------------------------------------ trava de promoção da IA

def gate_outcomes(n_days: int, edge: float, *, noise: float = 0.01, seed: int = 4, model: str = "G_GBM") -> pd.DataFrame:
    """Previsões maduras: 5 escolhas por dia com retorno = universo + `edge` + ruído; o resto do universo no próprio universo."""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2026-01-01", periods=n_days, freq="D", tz=UTC)
    rows = []
    for d in days:
        universe = float(rng.normal(0.0, 0.02))
        day_noise = float(rng.normal(0.0, noise))
        for k in range(8):
            top = k < 5
            rows.append({"model": model, "day": d, "symbol": f"C{k}/USDT", "prob": 0.9 - k * 0.05, "in_top_k": top, "target": 1.0,
                         "forward_30": universe + (edge + day_noise if top else 0.0), "universe_30": universe})
    return pd.DataFrame(rows)


def test_gate_approves_only_with_enough_days_and_a_positive_lower_bound() -> None:
    result = promotion_gate(pd.DataFrame(), gate_outcomes(120, edge=0.05), n_boot=400)
    assert result.status == GATE_APPROVED and result.approved
    assert result.ci_low > 0 and result.mean_excess > 0 and result.n_days == 120


def test_gate_rejects_when_the_edge_is_noise() -> None:
    out = gate_outcomes(120, edge=0.0, noise=0.05)
    out.loc[out["in_top_k"], "forward_30"] -= float(daily_excess(out).mean())   # amostra sem vantagem nenhuma (média exatamente 0)
    result = promotion_gate(pd.DataFrame(), out, n_boot=400)
    assert result.status == GATE_REJECTED and not result.approved
    assert result.ci_low < 0 < result.ci_high


def test_gate_rejects_a_model_that_loses_to_the_universe() -> None:
    result = promotion_gate(pd.DataFrame(), gate_outcomes(120, edge=-0.04), n_boot=400)
    assert result.status == GATE_REJECTED


def test_gate_needs_ninety_mature_days_even_with_a_huge_edge() -> None:
    result = promotion_gate(pd.DataFrame(), gate_outcomes(GATE_MIN_DAYS - 1, edge=0.20), n_boot=400)
    assert result.status == GATE_FEW_DAYS and not result.approved
    assert result.n_days == GATE_MIN_DAYS - 1 and np.isnan(result.ci_low)
    assert promotion_gate(pd.DataFrame(), gate_outcomes(GATE_MIN_DAYS, edge=0.20), n_boot=400).approved


def test_gate_with_no_data_is_insufficient() -> None:
    result = promotion_gate(pd.DataFrame(), pd.DataFrame(columns=["model", "day", "symbol", "in_top_k", "forward_30", "universe_30"]))
    assert result.status == GATE_FEW_DAYS and result.n_days == 0


def test_gate_is_deterministic() -> None:
    out = gate_outcomes(100, edge=0.02, noise=0.03)
    assert promotion_gate(pd.DataFrame(), out, n_boot=300) == promotion_gate(pd.DataFrame(), out, n_boot=300)


def test_gate_refuses_a_tampered_prediction_chain() -> None:
    base = pd.DataFrame({
        "day": [pd.Timestamp("2026-01-01", tz=UTC)] * 2, "symbol": ["A/USDT", "B/USDT"], "model": "G_GBM", "model_version": "v",
        "prob": [0.6, 0.4], "rank": [1, 2], "in_top_k": [True, True], "n_universe": [2, 2], "n_train": [10, 10],
        "train_end": pd.Timestamp("2025-11-01", tz=UTC), "run_ts": pd.Timestamp("2026-01-02", tz=UTC),
        "data_fingerprint": "f", "code_version": "c",
    })
    log = chain_rows(pd.DataFrame(), base)
    assert verify_chain(log) == []
    assert promotion_gate(log, gate_outcomes(120, edge=0.05), n_boot=300).approved
    forged = log.copy()
    forged.loc[0, "prob"] = 0.99
    result = promotion_gate(forged, gate_outcomes(120, edge=0.05), n_boot=300)
    assert result.status == GATE_BAD_CHAIN and not result.approved and result.problems


def test_ai_uses_the_main_model_and_falls_back_only_on_days_it_is_missing() -> None:
    main = gate_outcomes(3, edge=0.1, model="G_GBM")
    fallback = gate_outcomes(5, edge=-0.1, model="G_GBM_SEM_FNG")
    excess = daily_excess(pd.concat([main, fallback], ignore_index=True))
    assert len(excess) == 5
    assert (excess.iloc[:3] > 0.05).all() and (excess.iloc[3:] < -0.05).all()
    other = gate_outcomes(5, edge=0.5, model="F_LOGIT")
    assert daily_excess(other).empty


def pred_today(model: str, ranks: dict[str, int], day: str = "2026-11-05") -> pd.DataFrame:
    return pd.DataFrame({"day": pd.Timestamp(day, tz=UTC), "symbol": list(ranks), "model": model, "rank": list(ranks.values())})


def test_ai_picks_are_the_top_five_of_the_latest_day_in_rank_order() -> None:
    today = pred_today("G_GBM", {f"C{i}/USDT": 8 - i for i in range(8)})
    assert ai_picks_today(today) == ["C7/USDT", "C6/USDT", "C5/USDT", "C4/USDT", "C3/USDT"]
    assert ai_picks_today(pd.DataFrame()) == []


def assessed_frame() -> pd.DataFrame:
    rows = [("BTC/USDT", "MODERADA", True, 1), ("ETH/USDT", "AGUARDAR", False, None), ("SOL/USDT", "EVITAR", False, None),
            ("NEAR/USDT", "BOA_RELATIVA", True, 2), ("ADA/USDT", "AGUARDAR", False, None)]
    return pd.DataFrame({
        "symbol": [r[0] for r in rows], "opportunity": [r[1] for r in rows], "selected": [r[2] for r in rows],
        "candidate_rank": pd.array([r[3] for r in rows], dtype="Int64"),
        "reasons": [["motivo"] for _ in rows], "score": [80.0, 50.0, 10.0, 90.0, 55.0],
    })


def test_approved_ai_replaces_the_coins_and_keeps_the_hard_filters() -> None:
    out = apply_ai_selection(assessed_frame(), ["SOL/USDT", "ADA/USDT", "ETH/USDT", "BTC/USDT"], regime="FAVORAVEL",
                             regime_filter="bloquear", max_candidates=3)
    chosen = out[out["selected"]]
    assert chosen["symbol"].tolist() == ["ADA/USDT", "ETH/USDT", "BTC/USDT"]   # SOL é EVITAR: nunca entra
    assert chosen["candidate_rank"].tolist() == [1, 2, 3]
    assert not out.loc[out["symbol"].eq("NEAR/USDT"), "selected"].item()      # a regra antiga deixa de decidir
    assert chosen["opportunity"].isin(["BOA_RELATIVA", "MODERADA"]).all()
    assert all("IA (em teste)" in r[0] for r in chosen["reasons"])


def test_ai_selection_never_buys_in_a_blocked_defensive_market() -> None:
    out = apply_ai_selection(assessed_frame(), ["BTC/USDT", "ETH/USDT"], regime="DEFENSIVO", regime_filter="bloquear",
                             max_candidates=3)
    assert not out["selected"].any()


def test_ai_status_table_is_one_plain_row_and_documents_the_criterion() -> None:
    gate = promotion_gate(pd.DataFrame(), gate_outcomes(30, edge=0.05), n_boot=300)
    table = ai_status_table(gate, ["NEAR/USDT", "SOL/USDT"])
    assert list(table.columns) == list(AI_STATUS_SCHEMA) and len(table) == 1
    row = table.iloc[0]
    assert row["status"] == GATE_FEW_DAYS and not row["approved"] and row["picks"] == "NEAR, SOL"
    assert "IA (em teste)" in row["message"] and "30 de 90" in row["message"]
    assert row["criterion"] == GATE_ID
    approved = ai_status_table(promotion_gate(pd.DataFrame(), gate_outcomes(120, edge=0.05), n_boot=300), [])
    assert "aprovada" in approved["message"].iloc[0]


def test_gate_criterion_is_written_in_docs_before_use() -> None:
    doc = (Path(__file__).resolve().parent.parent / "docs" / "promocao_ia.md").read_text(encoding="utf-8")
    assert GATE_ID in doc and "pelo menos 90" in doc and "90%" in doc and "Nunca há ordem real" in doc


def _synthetic_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    candles = synthetic_candles()
    write_ohlcv(candles)
    write_fng(synthetic_fng(candles))


def test_pipeline_publishes_the_ai_state_and_the_ai_does_not_choose_coins_before_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synthetic_run(tmp_path, monkeypatch)
    result = pipeline.analyze(RUN_TS)
    status = result["ai_status"].iloc[0]
    assert status["status"] == GATE_FEW_DAYS and not status["approved"] and status["criterion"] == GATE_ID
    assert (tmp_path / "frontend" / "public" / "ai_status.parquet").is_file()
    assert not any("IA (em teste)" in r[0] for r in result["signals"]["reasons"] if len(r))
    assert "IA (em teste)" in pipeline.format_ai_line(result["ai_status"])  # type: ignore[attr-defined]
    assert not any("trava de promoção falhou" in n for n in result["shadow_notes"]["note"])


def test_pipeline_lets_the_ai_choose_the_simulated_coins_only_when_the_gate_approves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _synthetic_run(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    real = pipeline.apply_ai_selection

    def spy(assessed: pd.DataFrame, picks: list[str], **kwargs: object) -> pd.DataFrame:
        calls.append(list(picks))
        return real(assessed, picks, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pipeline, "apply_ai_selection", spy)
    pipeline.analyze(RUN_TS)
    assert calls == []                                            # sem aprovação a IA nunca escolhe moedas

    approved = pipeline.GateResult(GATE_APPROVED, 120, 90, 0.03, 0.01, 0.05)
    monkeypatch.setattr(pipeline, "evaluate_gate", lambda log, panel: (approved, []))
    result = pipeline.analyze(RUN_TS)
    expected = result["shadow_predictions"].query("model == 'G_GBM'").sort_values("rank")["symbol"].head(5).tolist()
    assert calls == [expected]                                    # aprovada: as escolhas são as da IA, na ordem dela
    assert result["ai_status"]["approved"].item() is True
    chosen = result["signals"][result["signals"]["selected"]]
    assert set(chosen["symbol"]) <= set(expected)                 # filtros duros mantidos (mercado sintético é defensivo)
    assert float(result["recommendation"]["total_brl"].iloc[0]) <= float(result["recommendation"]["budget_brl"].iloc[0])
