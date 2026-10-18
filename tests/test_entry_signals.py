"""Sinais de entrada candidatos: truncagem (sem dado futuro), evento = entrada na condição, execução na abertura."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.transformers.entry_signals import (
    EXECUTION_CLOSE,
    EXECUTION_OPEN,
    KIND_CROSS,
    KIND_TIMING,
    EntryRules,
    Panel,
    build_panel,
    combos,
    conditions,
    entries,
    event_counts,
    forward_returns,
    selection_scores,
    top_k,
    universe_reference,
)
from src.transformers.universe_pit import PitRules

PIT = PitRules(min_history_days=20, min_avg_quote_volume=1_000.0, volume_window_days=10, max_stale_days=1, max_size=50)
RULES = EntryRules(top_k=2, pit=PIT)
SYMBOLS = ("BTC/USDT", "AAA/USDT", "BBB/USDT", "CCC/USDT", "DDD/USDT")


def _candles(days: int = 420, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=days, freq="D", tz="UTC")
    frames = []
    for i, symbol in enumerate(SYMBOLS):
        close = 10.0 * np.exp(np.cumsum(rng.normal(0.001 * i, 0.04, days)))
        open_ = close * np.exp(rng.normal(0, 0.01, days))
        frames.append(pd.DataFrame({
            "timestamp": idx, "symbol": symbol, "open": open_, "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99, "close": close,
            "quote_volume": rng.uniform(5e6, 9e7, days) * (1 + i),
        }))
    return pd.concat(frames, ignore_index=True)


def test_grade_fechada_com_onze_combinacoes() -> None:
    grid = combos()
    assert [c.combo_id for c in grid] == ["A_30", "A_60", "A_90", "B_10", "B_15", "B_20", "C", "D_30", "D_60", "D_90", "E"]
    kinds = {c.combo_id: c.kind for c in grid}
    assert {k for k, v in kinds.items() if v == KIND_TIMING} == {"B_10", "B_15", "B_20", "C"}
    assert all(kinds[k] == KIND_CROSS for k in ("A_30", "D_90", "E"))


def test_evento_e_a_entrada_na_condicao_nao_cada_dia() -> None:
    idx = pd.date_range("2021-01-01", periods=8, freq="D", tz="UTC")
    active = pd.DataFrame({"X": [False, True, True, True, False, True, True, False]}, index=idx)
    ev = entries(active)
    assert ev["X"].tolist() == [False, True, False, False, False, True, False, False]


def test_recuo_b_gera_um_evento_por_episodio() -> None:
    """Uma moeda que fica 15% abaixo da máxima por vários dias seguidos gera um único evento de B."""
    n = 140
    idx = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")
    close = np.linspace(50.0, 100.0, n)        # tendência de alta: acima da SMA 100
    close[120:127] = 77.0                      # ~17% abaixo da máxima (~93) por 7 dias
    close[127:] = np.linspace(100.0, 101.0, n - 127)
    candles = pd.DataFrame({"timestamp": idx, "symbol": "BTC/USDT", "open": close, "high": close, "low": close,
                            "close": close, "quote_volume": 1e8})
    cond = conditions(build_panel(candles, RULES), RULES)
    on = cond["B_15"].active["BTC/USDT"]
    assert int(on.sum()) == 7
    ev = entries(cond["B_15"].active)["BTC/USDT"]
    assert int(ev.sum()) == 1 and bool(ev.iloc[120])


def test_top_k_respeita_o_universo_e_ignora_nan() -> None:
    idx = pd.date_range("2021-01-01", periods=1, freq="D", tz="UTC")
    values = pd.DataFrame({"A": [5.0], "B": [9.0], "C": [np.nan], "D": [7.0]}, index=idx)
    mask = pd.DataFrame({"A": [True], "B": [False], "C": [True], "D": [True]}, index=idx)
    out = top_k(values, mask, 2)
    assert out.iloc[0].to_dict() == {"A": True, "B": False, "C": False, "D": True}


@pytest.mark.parametrize("cut", ["2020-06-15", "2020-09-30", "2021-01-20"])
def test_truncagem_nao_muda_condicoes_nem_score(cut: str) -> None:
    """A linha de `t` (condições e score E) não depende de nenhum dado depois de `t`."""
    candles = _candles()
    day = pd.Timestamp(cut, tz="UTC")
    full_panel = build_panel(candles, RULES)
    cut_candles = candles[candles["timestamp"].le(day)]
    cut_panel = build_panel(cut_candles, RULES)
    full = conditions(full_panel, RULES, selection_scores(candles, full_panel.member))
    part = conditions(cut_panel, RULES, selection_scores(cut_candles, cut_panel.member))
    assert set(full) == {c.combo_id for c in combos(RULES)}
    for key, cond in full.items():
        pd.testing.assert_series_equal(cond.active.loc[day], part[key].active.loc[day], check_names=False)
        pd.testing.assert_series_equal(cond.calculable.loc[day], part[key].calculable.loc[day], check_names=False)
    s_full = selection_scores(candles, full_panel.member).loc[day]
    s_part = selection_scores(cut_candles, cut_panel.member).loc[day]
    pd.testing.assert_series_equal(s_full, s_part, check_names=False)


def test_score_e_existe_quando_ha_historico() -> None:
    candles = _candles()
    panel = build_panel(candles, RULES)
    scores = selection_scores(candles, panel.member)
    assert scores.iloc[-1].notna().sum() >= 3
    assert scores.iloc[:200].notna().sum().sum() == 0  # menos de 250 candles: não pontua


def _panel_one(open_: list[float], close: list[float], delisted: tuple[str, ...] = ()) -> Panel:
    idx = pd.date_range("2021-01-01", periods=len(close), freq="D", tz="UTC")
    o = pd.DataFrame({"X": open_}, index=idx)
    c = pd.DataFrame({"X": close}, index=idx)
    zero = pd.DataFrame({"X": 0.0}, index=idx)
    return Panel(o, c, c * 0 + 1e9, c.notna(), zero, delisted)


def test_retorno_futuro_usa_aberturas_de_t_mais_1_e_t_mais_1_mais_h() -> None:
    panel = _panel_one([10, 20, 30, 40, 50, 60], [11, 21, 31, 41, 51, 61])
    fwd = forward_returns(panel, 2, EXECUTION_OPEN)["X"]
    assert fwd.iloc[0] == pytest.approx(40 / 20 - 1)   # entra na abertura de t+1 (20), sai na de t+3 (40)
    assert fwd.iloc[2] == pytest.approx(60 / 40 - 1)
    assert fwd.iloc[3:].isna().all()                   # janela incompleta de moeda ativa: descartada
    close = forward_returns(panel, 2, EXECUTION_CLOSE)["X"]
    assert close.iloc[0] == pytest.approx(41 / 21 - 1)


def test_custos_nos_dois_lados_no_dia_da_entrada() -> None:
    panel = _panel_one([10, 10, 10, 10], [10, 10, 10, 10])
    idx = panel.close.index
    costly = Panel(panel.open, panel.close, panel.quote_volume, panel.member,
                   pd.DataFrame({"X": [0.0, 0.01, 0.5, 0.5]}, index=idx), ())
    fwd = forward_returns(costly, 1, EXECUTION_OPEN)["X"]
    assert fwd.iloc[0] == pytest.approx(0.99**2 - 1)


def test_deslistada_sai_ao_ultimo_preco() -> None:
    nan = float("nan")
    panel = _panel_one([10, 20, 30, nan, nan], [11, 21, 33, nan, nan], delisted=("X",))
    fwd = forward_returns(panel, 3, EXECUTION_OPEN)["X"]
    assert fwd.iloc[0] == pytest.approx(33 / 20 - 1)   # sem abertura em t+4: último fechamento


def test_referencia_do_universo_e_media_igual_do_dia() -> None:
    idx = pd.date_range("2021-01-01", periods=2, freq="D", tz="UTC")
    fwd = pd.DataFrame({"A": [0.10, 0.0], "B": [0.30, np.nan], "C": [5.0, 1.0]}, index=idx)
    member = pd.DataFrame({"A": [True, True], "B": [True, True], "C": [False, True]}, index=idx)
    ref = universe_reference(fwd, member)
    assert ref.iloc[0] == pytest.approx(0.20)          # C fora do universo
    assert ref.iloc[1] == pytest.approx(0.50)          # B sem janela completa


def test_contagem_de_eventos_nao_olha_retorno() -> None:
    idx = pd.date_range("2021-01-01", periods=4, freq="D", tz="UTC")
    ev = {"A_30": pd.DataFrame({"X": [True, False, True, False], "Y": [False] * 4}, index=idx)}
    out = event_counts(ev)
    assert out.iloc[0].to_dict() == {"combo": "A_30", "n_events": 2, "n_coins": 1}
