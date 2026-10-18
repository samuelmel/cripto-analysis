"""Sinais de entrada no produto: COMPRAR só com sinal VALIDADO, PROMISSOR só observa, falha fechada e mudanças."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.loaders.evidence_store import read_entry_levels
from src.transformers.entry_live import (
    CHANGE_FIRED,
    CHANGE_UNDONE,
    ENTRY_SCHEMA,
    active_levels,
    apply_entry_signals_to_stage,
    attach_entry_status,
    buy_mask,
    empty_levels,
    entry_changes,
    entry_status,
)
from src.transformers.entry_signals import Condition
from src.transformers.entry_study import LEVEL_SCHEMA

IDX = pd.date_range("2026-10-01", periods=6, freq="D", tz="UTC")
DAY = IDX[-1]


def _levels(rows: dict[str, str]) -> pd.DataFrame:
    frame = empty_levels()
    for combo, level in rows.items():
        frame.loc[len(frame), ["combo", "candidate", "kind", "level"]] = [combo, combo[0], "SELECAO", level]
    return frame.astype({c: t for c, t in LEVEL_SCHEMA.items() if c in ("combo", "candidate", "kind", "level")})


def _cond(values: dict[str, list[bool]]) -> Condition:
    active = pd.DataFrame(values, index=IDX)
    return Condition(active, pd.DataFrame(True, index=IDX, columns=active.columns))


CONDS = {
    "E": _cond({"AAA/USDT": [False, True, True, True, True, True], "BBB/USDT": [False] * 5 + [True],
                "CCC/USDT": [True] * 5 + [False]}),
    "C": _cond({"AAA/USDT": [False] * 6, "BBB/USDT": [False] * 4 + [True, True], "CCC/USDT": [False] * 6}),
}


def test_so_validado_e_promissor_contam() -> None:
    lv = _levels({"E": "PROMISSOR", "C": "VALIDADO", "A_30": "SEM_EVIDENCIA"})
    assert active_levels(lv) == {"E": "PROMISSOR", "C": "VALIDADO"}
    assert active_levels(empty_levels()) == {}


def test_estado_do_dia() -> None:
    lv = _levels({"E": "PROMISSOR", "C": "VALIDADO"})
    st = entry_status(CONDS, lv, ["AAA/USDT", "BBB/USDT", "CCC/USDT"], DAY).set_index("symbol")
    assert st.loc["AAA/USDT", "entry_level"] == "PROMISSOR"
    assert not bool(st.loc["AAA/USDT", "entry_new"])
    assert st.loc["AAA/USDT", "entry_since"] == IDX[1]
    assert st.loc["BBB/USDT", "entry_level"] == "VALIDADO"       # o melhor nível entre as condições ativas
    assert list(st.loc["BBB/USDT", "entry_combos"]) == ["C", "E"]
    assert bool(st.loc["BBB/USDT", "entry_new"]) and st.loc["BBB/USDT", "entry_since"] == IDX[4]
    assert pd.isna(st.loc["CCC/USDT", "entry_level"]) and list(st.loc["CCC/USDT", "entry_combos"]) == []


def test_combinacao_sem_nivel_e_ignorada() -> None:
    st = entry_status(CONDS, _levels({"E": "SEM_EVIDENCIA"}), ["AAA/USDT"], DAY)
    assert pd.isna(st["entry_level"].iloc[0])


def test_comprar_so_com_validado_e_sma200_sempre_rebaixada() -> None:
    history = pd.DataFrame({
        "timestamp": [DAY, DAY, DAY, IDX[0]],
        "symbol": pd.array(["AAA/USDT", "BBB/USDT", "CCC/USDT", "AAA/USDT"], dtype="string"),
        "stage": pd.array(["COMPRAR", "NEUTRO", "PREPARAR", "COMPRAR"], dtype="string"),
    })
    promising_only = _levels({"E": "PROMISSOR"})
    assert buy_mask(CONDS, promising_only) is None
    out = apply_entry_signals_to_stage(history, buy_mask(CONDS, promising_only))
    assert out["stage"].tolist() == ["NEUTRO", "NEUTRO", "NEUTRO", "NEUTRO"]  # PROMISSOR nunca vira COMPRAR
    validated = _levels({"C": "VALIDADO"})
    out = apply_entry_signals_to_stage(history, buy_mask(CONDS, validated))
    assert out["stage"].tolist() == ["NEUTRO", "COMPRAR", "NEUTRO", "NEUTRO"]


def test_mudancas_disparou_e_desfez() -> None:
    ch = entry_changes(CONDS, _levels({"E": "PROMISSOR"}), ["AAA/USDT", "BBB/USDT", "CCC/USDT"], DAY)
    got = {(r.symbol, r.change) for r in ch.itertuples()}
    assert got == {("BBB/USDT", CHANGE_FIRED), ("CCC/USDT", CHANGE_UNDONE)}
    assert entry_changes(CONDS, empty_levels(), ["AAA/USDT"], DAY).empty


def test_sinais_sem_estado_ficam_sem_sinal() -> None:
    signals = pd.DataFrame({"symbol": pd.array(["AAA/USDT", "ZZZ/USDT"], dtype="string"), "close": [1.0, 2.0]})
    status = entry_status(CONDS, _levels({"E": "PROMISSOR"}), ["AAA/USDT"], DAY)
    out = attach_entry_status(signals, status)
    assert set(ENTRY_SCHEMA) <= set(out.columns)
    z = out[out["symbol"].eq("ZZZ/USDT")].iloc[0]
    assert pd.isna(z["entry_level"]) and list(z["entry_combos"]) == [] and not bool(z["entry_new"])
    empty = attach_entry_status(signals, None)
    assert empty["entry_level"].isna().all()


def test_niveis_ausentes_ou_ilegiveis_falham_fechado(tmp_path: Path) -> None:
    assert read_entry_levels(tmp_path / "nao_existe.parquet").empty
    bad = tmp_path / "ruim.parquet"
    pd.DataFrame({"x": [1]}).to_parquet(bad)
    assert read_entry_levels(bad).empty


def test_niveis_versionados_tem_e_promissor_e_nenhum_validado() -> None:
    lv = read_entry_levels()
    assert not lv.empty, "evidence/entry_signals/entry_signal_levels.parquet ausente"
    assert active_levels(lv) == {"E": "PROMISSOR"}


@pytest.mark.parametrize("col", list(ENTRY_SCHEMA))
def test_schema_de_saida_tem_as_colunas_de_entrada(col: str) -> None:
    from src.transformers.recommendation import SIGNALS_SCHEMA

    assert SIGNALS_SCHEMA[col] == ENTRY_SCHEMA[col]
