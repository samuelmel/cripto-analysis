"""Previsão: sem vazamento do futuro, escolha só na validação, baseline honesto, saída declarada."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.transformers import forecast as fc
from src.transformers.forecast import FORECAST_SCHEMA, ForecastRules, forecast_table

VALIDATION = (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2022-12-31", tz="UTC"))
TEST = (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2026-12-31", tz="UTC"))
FAST = ForecastRules(windows=(90, 180), blocks=(5, 10), ewma_lambdas=(0.94, 0.97), sims=200)


def closes(drift: float = 0.0, vol: float = 0.02, seed: int = 7, days: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2018-01-01", periods=days, freq="D", tz="UTC")
    out = {}
    for k, symbol in enumerate(("BTC/USDT", "ETH/USDT")):
        lr = drift + vol * np.random.default_rng(seed + k).standard_normal(days) + 0 * rng.random()
        out[symbol] = 100.0 * np.exp(np.cumsum(lr))
    return pd.DataFrame(out, index=index)


def table(frame: pd.DataFrame, seed: int = 1, horizons: tuple[int, ...] = (1, 7)) -> pd.DataFrame:
    return forecast_table(frame, ("BTC/USDT", "ETH/USDT"), VALIDATION, TEST, seed, horizons, FAST)


def test_schema_and_shape() -> None:
    out = table(closes())
    assert list(out.columns) == list(FORECAST_SCHEMA)
    assert {str(c): str(t) for c, t in out.dtypes.items()}["horizon_days"] == "int64"
    assert len(out) == 2 * 2 * 2  # 2 ativos × 2 horizontes × (baseline + modelo)
    assert set(out["role"]) == {"BASELINE", "MODELO"}
    assert (out[out["role"].eq("BASELINE")]["method"] == "PASSEIO_ALEATORIO").all()
    assert (out["p10_pct"] <= out["p50_pct"]).all() and (out["p50_pct"] <= out["p90_pct"]).all()
    assert (out["p10_price"] > 0).all()
    assert (out["n_eval"] > 0).all()
    assert (out["coverage_nominal"] == 0.8).all()


def test_same_seed_same_result_and_no_clock() -> None:
    frame = closes()
    pd.testing.assert_frame_equal(table(frame, seed=5), table(frame, seed=5))


def test_bootstrap_depends_on_the_injected_seed() -> None:
    lr = np.random.default_rng(0).standard_normal(500) * 0.02
    predict = fc._bootstrap(lr, h=7, window=365, block=5, sims=300)
    a = predict(400, np.random.default_rng([1]))
    assert a == predict(400, np.random.default_rng([1]))
    assert a != predict(400, np.random.default_rng([2]))


def test_predictors_never_use_data_after_the_origin() -> None:
    lr = np.random.default_rng(3).standard_normal(600) * 0.02
    changed = lr.copy()
    changed[301:] += 5.0  # futuro absurdo depois da origem 300
    origin = 300
    builders = {
        "rw": lambda x: fc._random_walk(x, 7, 180),
        "boot": lambda x: fc._bootstrap(x, 7, 180, 5, 200),
        "ewma": lambda x: fc._ewma(x, 7, 180, 0.94),
    }
    for name, build in builders.items():
        before = build(lr)(origin, np.random.default_rng([9]))
        after = build(changed)(origin, np.random.default_rng([9]))
        assert before == after, name


def test_origins_realized_window_stays_inside_the_period() -> None:
    days = pd.DatetimeIndex(pd.date_range("2018-01-01", periods=3000, freq="D", tz="UTC"))
    for h in (1, 7, 30):
        origins = fc._origins(days, len(days), h, VALIDATION)
        assert days[origins[-1] + h] <= VALIDATION[1]
        assert days[origins[0]] >= VALIDATION[0]
        assert all(b - a == h for a, b in zip(origins, origins[1:], strict=False))


def test_test_period_never_influences_the_choice() -> None:
    base = closes()
    shocked = base.copy()
    after = shocked.index > pd.Timestamp("2022-12-31", tz="UTC") + pd.Timedelta(days=40)
    shocked.loc[after, :] = shocked.loc[after, :] * np.linspace(1.0, 6.0, int(after.sum()))[:, None]
    a, b = table(base), table(shocked)
    keys = ["symbol", "horizon_days", "role", "method", "params"]
    pd.testing.assert_frame_equal(a[keys], b[keys])  # mesmos parâmetros escolhidos
    assert not np.allclose(a["rmse_pct"], b["rmse_pct"])  # mas o teste mede coisas diferentes


def test_noise_has_no_demonstrated_edge_and_baseline_is_calibrated() -> None:
    out = table(closes(drift=0.0, vol=0.02), horizons=(1,))
    assert not out["beats_baseline"].any()
    model = out[out["role"].eq("MODELO")]
    assert model["verdict"].str.contains("sem vantagem demonstrada sobre o preço de hoje").all()
    base = out[out["role"].eq("BASELINE")]
    assert base["coverage"].between(0.77, 0.83).all()  # faixa nominal de 80% bate com o ruído gaussiano
    assert base["coverage_ok"].all()
    assert base["verdict"].str.startswith("referência").all()


def test_a_real_edge_is_detected() -> None:
    # Tendência forte e constante: o modelo (com tendência) deve vencer o passeio sem tendência.
    out = table(closes(drift=0.01, vol=0.002), horizons=(7,))
    model = out[out["role"].eq("MODELO")]
    assert model["beats_baseline"].all()
    assert (model["rmse_pct"] < model["base_rmse_pct"]).all()
    assert (model["mae_pct"] < model["base_mae_pct"]).all()
    assert (model["pinball_pct"] < model["base_pinball_pct"]).all()


def test_baseline_columns_are_the_baseline_rows() -> None:
    out = table(closes(), horizons=(7,))
    for _, group in out.groupby("symbol"):
        base = group[group["role"].eq("BASELINE")].iloc[0]
        model = group[group["role"].eq("MODELO")].iloc[0]
        assert model["base_rmse_pct"] == base["rmse_pct"]
        assert model["base_coverage"] == base["coverage"]
        assert model["base_pinball_pct"] == base["pinball_pct"]


def test_insufficient_history_gives_no_rows_instead_of_a_made_up_forecast() -> None:
    short = closes(days=400)
    out = table(short)
    assert out.empty
    assert list(out.columns) == list(FORECAST_SCHEMA)


def test_pinball_loss_is_zero_for_a_perfect_forecast_and_scores_mae_for_the_median() -> None:
    y = np.array([0.01, -0.02, 0.03])
    assert fc._pinball(y, y, y, y) == 0.0
    flat = np.zeros(3)
    assert fc._score(y, flat - 1, flat, flat + 1).mae == np.mean(np.abs(y))
