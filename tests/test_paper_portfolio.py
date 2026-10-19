"""Carteiras simuladas da IA: fatias de 30 dias, referências, regra de parada, placar e mensagem."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.backtest_engine import ExecutionConfig, panel_from_candles
from src.transformers.costs import CostModel
from src.transformers.data_quality import clean_candles
from src.transformers.entry_signals import EntryRules, build_panel, trailing_return
from src.transformers.notification import format_paper_report, validate_messages
from src.transformers.paper_portfolio import (
    REF_MARKET,
    REF_MOMENTUM,
    STATUS_DISCARDED,
    STATUS_TESTING,
    STATUS_TOO_EARLY,
    PaperRules,
    run_paper,
    status,
    track_record,
    tranche_weights,
)
from tests.synthetic_market import RUN_TS, synthetic_candles

UTC = "UTC"


def test_one_day_of_picks_is_a_tranche_of_one_thirtieth_for_thirty_days() -> None:
    idx = pd.date_range("2026-01-01", periods=40, freq="D", tz=UTC)
    picks = pd.DataFrame(False, index=idx, columns=["A", "B"])
    picks.loc[idx[0], ["A", "B"]] = True
    w = tranche_weights(picks, idx, hold_days=30)
    assert w.loc[idx[0], "A"] == pytest.approx(1 / 30 / 2)
    assert w.loc[idx[29], "B"] == pytest.approx(1 / 30 / 2) and w.loc[idx[30]].sum() == 0
    every_day = tranche_weights(pd.DataFrame(True, index=idx, columns=["A", "B"]), idx, hold_days=30)
    assert every_day.sum(axis=1).max() == pytest.approx(1.0) and every_day.sum(axis=1).iloc[9] == pytest.approx(10 / 30)


def test_stop_rule() -> None:
    r = PaperRules()
    assert status("G_GBM", 10, -40.0, r) == STATUS_TOO_EARLY
    assert status("G_GBM", 100, -40.0, r) == STATUS_TESTING          # antes de 182 dias nada é descartado
    assert status("G_GBM", 200, -16.0, r) == STATUS_DISCARDED
    assert status("G_GBM", 200, -10.0, r) == STATUS_TESTING
    assert status(REF_MARKET, 200, 0.0, r) == "REFERENCIA"


def _log(candles: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    coins = sorted(candles["symbol"].unique())[:3]
    rows = [{"day": d, "symbol": c, "model": "G_GBM", "in_top_k": True, "prob": 0.6, "rank": i + 1}
            for d in days for i, c in enumerate(coins)]
    return pd.DataFrame(rows)


def test_paper_portfolios_reconcile_and_include_both_references() -> None:
    candles = clean_candles(synthetic_candles())
    panel = build_panel(candles, EntryRules())
    market = panel_from_candles(candles, CostModel())
    days = pd.date_range("2026-03-01", "2026-04-30", freq="D", tz=UTC)
    result = run_paper(_log(candles, days), market, panel.member, trailing_return(panel.close, 90),
                       ExecutionConfig(costs=CostModel()))
    s = result.summary.set_index("portfolio")
    assert {"G_GBM", REF_MARKET, REF_MOMENTUM} <= set(s.index)
    assert s.loc["G_GBM", "start"] == days[0]
    assert s.loc[REF_MARKET, "vs_market_pp"] == pytest.approx(0.0)
    assert (result.equity.iloc[0] <= 1.0 + 1e-12).all()           # nada rende antes da primeira execução
    assert s.loc["G_GBM", "invested_pct"] < 100.0                  # entra em fatias, não de uma vez
    assert s.loc["G_GBM", "cost_pct"] > 0


def test_track_record_counts_only_bought_coins() -> None:
    outcomes = pd.DataFrame({"model": ["M", "M", "M"], "day": pd.to_datetime(["2026-01-01"] * 3, utc=True),
                             "symbol": ["A", "B", "C"], "prob": [0.9, 0.8, 0.1], "in_top_k": [True, True, False],
                             "target": [1.0, 0.0, 1.0], "forward_30": [0.10, 0.0, 0.5], "universe_30": [0.02, 0.02, 0.02]})
    t = track_record(outcomes).set_index("model")
    assert t.loc["M", "n_mature"] == 2 and t.loc["M", "hit_rate_pct"] == pytest.approx(50.0)
    assert t.loc["M", "mean_excess_pp"] == pytest.approx(3.0)


def test_message_says_it_is_a_simulation_and_passes_validation() -> None:
    shadow = pd.DataFrame({"model": ["G_GBM"] * 2, "symbol": ["SOL/USDT", "BTC/USDT"], "rank": [2, 1]})
    summary = pd.DataFrame({"portfolio": ["G_GBM", REF_MARKET], "label": ["Boosting", "Mercado"],
                            "start": pd.to_datetime(["2026-10-20"] * 2, utc=True), "n_days": [5, 5],
                            "total_return_pct": [1.5, 0.5], "vs_market_pp": [1.0, 0.0], "status": ["INICIO", "REFERENCIA"]})
    texts = format_paper_report(shadow, summary, None, now=RUN_TS, labels={"G_GBM": "Boosting"})
    joined = "\n".join(texts)
    assert "SIMULAÇÃO (sem dinheiro real)" in joined and "Boosting: BTC, SOL" in joined
    assert "+1,0 pp contra o mercado" in joined and "não é recomendação" in joined
    assert "Nenhuma previsão completou 30 dias" in joined
    assert validate_messages(texts, ["segredo"]) == []
    assert format_paper_report(None, None, None, now=RUN_TS) == []


def test_pipeline_shows_the_simulation_in_telegram_without_touching_the_recommendation(
    tmp_path: "object", monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from src import pipeline
    from src.loaders.market_store import write_fng, write_ohlcv
    from tests.synthetic_market import synthetic_fng

    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    candles = synthetic_candles()
    write_ohlcv(candles)
    write_fng(synthetic_fng(candles))
    result = pipeline.analyze(RUN_TS)
    assert not result["paper_summary"].empty
    assert set(result["paper_summary"]["portfolio"]) >= {REF_MARKET, REF_MOMENTUM}
    assert pipeline._notify(result, RUN_TS.to_pydatetime(), dry_run=True) == 0
    out = capsys.readouterr().out
    assert "IA EM TESTE" in out and "sem dinheiro real" in out
    assert "prob" not in result["recommendation"].columns
