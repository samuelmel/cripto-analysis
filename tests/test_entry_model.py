"""Modelo sombra F: sem vazamento (truncagem, expurgo, padronização do treino), IRLS determinístico e correto."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.entry_model import (
    FEATURES,
    PURGE_DAYS,
    fit_logistic,
    model_features,
    outperform_target,
    predict,
    probability_frame,
    stack_rows,
    walk_forward,
)
from src.transformers.entry_signals import EntryRules, build_panel
from src.transformers.universe_pit import PitRules

PIT = PitRules(min_history_days=20, min_avg_quote_volume=1_000.0, volume_window_days=10, max_stale_days=1, max_size=50)
RULES = EntryRules(top_k=2, pit=PIT)
SYMBOLS = ("BTC/USDT", "AAA/USDT", "BBB/USDT", "CCC/USDT")


def _candles(start: str = "2018-01-01", days: int = 1200, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days, freq="D", tz="UTC")
    frames = []
    for i, symbol in enumerate(SYMBOLS):
        close = 10.0 * np.exp(np.cumsum(rng.normal(0.0005 * i, 0.04, days)))
        frames.append(pd.DataFrame({"timestamp": idx, "symbol": symbol, "open": close * np.exp(rng.normal(0, 0.01, days)),
                                    "high": close * 1.02, "low": close * 0.98, "close": close,
                                    "quote_volume": rng.uniform(5e6, 5e7, days)}))
    return pd.concat(frames, ignore_index=True)


def _fng(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(np.arange(len(index)) % 100, index=index, dtype="float64")


def _rows(candles: pd.DataFrame) -> pd.DataFrame:
    panel = build_panel(candles, RULES)
    feats = model_features(panel, _fng(panel.close.index))
    return stack_rows(feats, outperform_target(panel, "BTC/USDT"), panel.member)


@pytest.mark.parametrize("cut", ["2019-03-01", "2020-06-30"])
def test_features_nao_mudam_com_a_truncagem(cut: str) -> None:
    candles = _candles()
    day = pd.Timestamp(cut, tz="UTC")
    full = build_panel(candles, RULES)
    part = build_panel(candles[candles["timestamp"].le(day)], RULES)
    f_full = model_features(full, _fng(full.close.index))
    f_part = model_features(part, _fng(part.close.index))
    assert set(f_full) == set(FEATURES)
    for name in FEATURES:
        pd.testing.assert_series_equal(f_full[name].loc[day], f_part[name].loc[day], check_names=False)


def test_nenhum_alvo_de_treino_termina_depois_do_corte() -> None:
    rows = _rows(_candles())
    _, folds = walk_forward(rows, (2019, 2020, 2021))
    assert len(folds) == 3
    for _, f in folds.iterrows():
        cut = pd.Timestamp(f"{int(f['year']) - 1}-12-31", tz="UTC")
        assert f["last_target_end"] <= cut
        assert f["train_end"] == cut - pd.Timedelta(days=PURGE_DAYS)


def test_dobra_nao_ve_dados_depois_do_expurgo() -> None:
    """Mudar alvos e features de qualquer linha depois de `train_end` (fora do ano previsto) não muda a previsão."""
    rows = _rows(_candles())
    base, _ = walk_forward(rows, (2020,))
    days = rows.index.get_level_values("timestamp")
    train_end = pd.Timestamp("2019-12-31", tz="UTC") - pd.Timedelta(days=PURGE_DAYS)
    tampered = rows.copy()
    late = (days > train_end) & (days.year != 2020)
    rng = np.random.default_rng(0)
    tampered.loc[late, "target"] = rng.integers(0, 2, int(late.sum())).astype("float64")
    tampered.loc[late, list(FEATURES)] = rng.normal(size=(int(late.sum()), len(FEATURES)))
    other, _ = walk_forward(tampered, (2020,))
    pd.testing.assert_series_equal(base, other)


def test_padronizacao_vem_so_do_treino() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(5.0, 2.0, size=(500, 3))
    y = (x[:, 0] + rng.normal(size=500) > 5.0).astype("float64")
    model = fit_logistic(x, y)
    assert model.mean == pytest.approx(x.mean(axis=0))
    assert model.std == pytest.approx(x.std(axis=0))
    test = rng.normal(50.0, 2.0, size=(10, 3))   # teste em outra escala: não re-padroniza
    assert predict(model, test)[0] == pytest.approx(predict(model, test[:1])[0])
    assert np.all(predict(model, test) > 0.99)


def test_irls_e_otimo_e_deterministico() -> None:
    rng = np.random.default_rng(2)
    x = rng.normal(size=(800, 4))
    true = np.array([1.5, -1.0, 0.0, 0.5])
    y = (rng.uniform(size=800) < 1 / (1 + np.exp(-(x @ true)))).astype("float64")
    a = fit_logistic(x, y, lam=1.0)
    b = fit_logistic(x, y, lam=1.0)
    assert np.array_equal(a.coef, b.coef)
    z = np.column_stack([np.ones(len(x)), (x - a.mean) / a.std])
    p = 1 / (1 + np.exp(-(z @ a.coef)))
    penalty = np.array([0.0, 1.0, 1.0, 1.0, 1.0])
    grad = z.T @ (y - p) - penalty * a.coef
    assert np.max(np.abs(grad)) < 1e-6        # condição de primeira ordem do problema penalizado
    assert np.sign(a.coef[1]) == 1 and np.sign(a.coef[2]) == -1
    strong = fit_logistic(x, y, lam=1e6)
    assert np.max(np.abs(strong.coef[1:])) < 0.01  # L2 forte encolhe tudo menos o intercepto


def test_linhas_so_do_universo_e_com_features_completas() -> None:
    candles = _candles()
    panel = build_panel(candles, RULES)
    rows = stack_rows(model_features(panel, None), outperform_target(panel, "BTC/USDT"), panel.member)
    assert rows.empty                          # sem Fear & Greed, nenhuma linha completa
    rows = _rows(candles)
    assert not rows[list(FEATURES)].isna().any().any()
    member = panel.member.stack(future_stack=True)
    assert bool(member.reindex(rows.index).all())


def test_probabilidade_em_formato_largo() -> None:
    idx = pd.date_range("2021-01-01", periods=2, freq="D", tz="UTC")
    prob = pd.Series([0.2, 0.7], index=pd.MultiIndex.from_tuples([(idx[0], "A"), (idx[1], "B")],
                                                                  names=["timestamp", "symbol"]))
    wide = probability_frame(prob, idx, pd.Index(["A", "B", "C"]))
    assert wide.loc[idx[1], "B"] == pytest.approx(0.7)
    assert np.isnan(wide.loc[idx[0], "C"])
