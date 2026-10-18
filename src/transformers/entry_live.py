"""Sinais de entrada no produto: estado de hoje, COMPRAR por sinal e mudanças da lista de observação.

Puro (CLAUDE.md §1). Regras (docs/entry_signals.md, "Consequência para o produto"):
    COMPRAR      a moeda está, no dia, na condição de uma combinação com nível VALIDADO no estudo agregado. Não depende
                 mais da moeda: a validação individual (`signal_validation`) vira só informação. O COMPRAR e o PREPARAR
                 antigos (regra SMA 200) são sempre rebaixados para NEUTRO.
    OBSERVAÇÃO   condição ativa de uma combinação PROMISSOR: aparece como candidata em observação, nunca como COMPRAR.
Sem a tabela de níveis (arquivo ausente ou ilegível), nenhuma combinação conta (falha fechada).

O universo do dia é o point-in-time calculado sobre os candles analisados (mesma regra do estudo). As condições são
calculadas para todos os dias, então ontem sai da mesma conta que hoje (a mudança não depende de estado gravado).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .anomaly_detector import STAGE_BUY, STAGE_NEUTRAL, STAGE_WATCH
from .entry_signals import Condition, EntryRules, build_panel, conditions, selection_scores
from .entry_study import LEVEL_PROMISING, LEVEL_SCHEMA, LEVEL_VALIDATED

ENTRY_SCHEMA: dict[str, str] = {
    "entry_level": "string",              # VALIDADO / PROMISSOR / nulo: o melhor nível entre as condições ativas hoje
    "entry_combos": "object",             # lista de str: combinações VALIDADO/PROMISSOR com a condição ativa hoje
    "entry_new": "bool",                  # alguma dessas combinações entrou na condição hoje
    "entry_since": "datetime64[ns, UTC]", # início do episódio ativo mais antigo entre elas
}

CHANGE_FIRED = "DISPAROU"
CHANGE_UNDONE = "DESFEZ"
CHANGE_SCHEMA: dict[str, str] = {"symbol": "string", "combo": "string", "level": "string", "change": "string"}

COMBO_TEXT: dict[str, str] = {
    "A_30": "entre as 5 maiores altas de 30 dias", "A_60": "entre as 5 maiores altas de 60 dias",
    "A_90": "entre as 5 maiores altas de 90 dias",
    "B_10": "recuo de 10% em tendência de alta", "B_15": "recuo de 15% em tendência de alta",
    "B_20": "recuo de 20% em tendência de alta",
    "C": "rompimento da máxima de 55 dias com volume",
    "D_30": "entre as 5 mais fortes contra o BTC em 30 dias", "D_60": "entre as 5 mais fortes contra o BTC em 60 dias",
    "D_90": "entre as 5 mais fortes contra o BTC em 90 dias",
    "E": "entre as 5 maiores notas do score de seleção",
    "F": "entre as 5 maiores probabilidades do modelo",
}


def empty_levels() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in LEVEL_SCHEMA.items()})


def active_levels(levels: pd.DataFrame) -> dict[str, str]:
    """Combinação -> nível, só para VALIDADO e PROMISSOR (as únicas que o produto usa)."""
    if levels.empty:
        return {}
    keep = levels[levels["level"].isin([LEVEL_VALIDATED, LEVEL_PROMISING])]
    return {str(c): str(lv) for c, lv in zip(keep["combo"], keep["level"], strict=True)}


def live_conditions(
    candles: pd.DataFrame, levels: pd.DataFrame, rules: EntryRules = EntryRules()
) -> dict[str, Condition]:
    """Condições, em todos os dias, das combinações VALIDADO/PROMISSOR. Sem nenhuma, não calcula nada."""
    wanted = active_levels(levels)
    if not wanted or candles.empty:
        return {}
    panel = build_panel(candles, rules)
    scores = selection_scores(candles, panel.member) if "E" in wanted else None
    every = conditions(panel, rules, scores)
    return {k: every[k] for k in wanted if k in every}


@dataclass(frozen=True)
class _Run:
    active: bool
    new: bool
    since: pd.Timestamp | None


def _run_on(active: pd.Series, day: pd.Timestamp) -> _Run:
    """Estado da condição em `day` para uma moeda: ativa, entrou hoje, início do episódio."""
    on = active.fillna(False).astype(bool)
    if day not in on.index or not bool(on.loc[day]):
        return _Run(False, False, None)
    flags = on.loc[:day].to_numpy(dtype=bool)
    off = np.flatnonzero(~flags)
    first = int(off[-1]) + 1 if len(off) else 0
    start = pd.Timestamp(on.index[first])
    return _Run(True, start == day, start)


def entry_status(conds: Mapping[str, Condition], levels: pd.DataFrame, symbols: Sequence[str], day: pd.Timestamp) -> pd.DataFrame:
    """Uma linha por moeda de `symbols` (ENTRY_SCHEMA + `symbol`) com o estado dos sinais em `day`."""
    lv = active_levels(levels)
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        combos: list[str] = []
        new = False
        starts: list[pd.Timestamp] = []
        for combo, cond in conds.items():
            if combo not in lv or symbol not in cond.active.columns:
                continue
            run = _run_on(cond.active[symbol], day)
            if not run.active or run.since is None:
                continue
            combos.append(combo)
            new = new or run.new
            starts.append(run.since)
        found = {lv[c] for c in combos}
        best = LEVEL_VALIDATED if LEVEL_VALIDATED in found else LEVEL_PROMISING if found else None
        since = min(starts) if starts else None
        rows.append({"symbol": symbol, "entry_level": best, "entry_combos": sorted(combos), "entry_new": new,
                     "entry_since": since})
    frame = pd.DataFrame(rows, columns=["symbol", *ENTRY_SCHEMA])
    return frame.astype({"symbol": "string", **ENTRY_SCHEMA})


def attach_entry_status(signals: pd.DataFrame, status: pd.DataFrame | None) -> pd.DataFrame:
    """Acrescenta as colunas de ENTRY_SCHEMA a `signals`; moeda sem estado fica sem sinal (nível nulo, lista vazia)."""
    base = signals.drop(columns=[c for c in ENTRY_SCHEMA if c in signals.columns])
    if status is None or status.empty:
        status = pd.DataFrame({"symbol": pd.Series(dtype="string"), **{c: pd.Series(dtype=t) for c, t in ENTRY_SCHEMA.items()}})
    out = base.merge(status.astype({"symbol": "string"}), on="symbol", how="left", validate="one_to_one")
    missing = out["entry_combos"].isna()
    out.loc[missing, "entry_combos"] = pd.Series([[] for _ in range(int(missing.sum()))], index=out.index[missing],
                                                 dtype="object")
    out["entry_new"] = out["entry_new"].fillna(False).astype(bool)
    return out.astype({c: t for c, t in ENTRY_SCHEMA.items() if c != "entry_combos"})


def buy_mask(conds: Mapping[str, Condition], levels: pd.DataFrame) -> pd.DataFrame | None:
    """True em (dia, moeda) com a condição de alguma combinação VALIDADO ativa; None se não há combinação VALIDADO."""
    validated = [k for k, lv in active_levels(levels).items() if lv == LEVEL_VALIDATED and k in conds]
    if not validated:
        return None
    mask = conds[validated[0]].active.fillna(False).astype(bool)
    for k in validated[1:]:
        mask = mask | conds[k].active.reindex_like(mask).fillna(False).astype(bool)
    return mask


def apply_entry_signals_to_stage(history: pd.DataFrame, mask: pd.DataFrame | None) -> pd.DataFrame:
    """COMPRAR por sinal: rebaixa o COMPRAR/PREPARAR da regra SMA 200 e marca COMPRAR onde `mask` é True."""
    stage = history["stage"].mask(history["stage"].isin([STAGE_BUY, STAGE_WATCH]), STAGE_NEUTRAL)
    if mask is not None and not history.empty:
        long = mask.stack(future_stack=True)
        keys = pd.MultiIndex.from_arrays([history["timestamp"], history["symbol"].astype(str)])
        hit = long.reindex(keys).fillna(False).to_numpy(dtype=bool)
        stage = stage.mask(pd.Series(hit, index=history.index), STAGE_BUY)
    return history.assign(stage=stage.astype(history["stage"].dtype))


def entry_changes(conds: Mapping[str, Condition], levels: pd.DataFrame, symbols: Sequence[str], day: pd.Timestamp) -> pd.DataFrame:
    """Combinações VALIDADO/PROMISSOR que dispararam (entraram na condição) ou se desfizeram (saíram) em `day`."""
    lv = active_levels(levels)
    prev = day - pd.Timedelta(days=1)
    rows = []
    for combo, cond in conds.items():
        if combo not in lv:
            continue
        frame = cond.active.fillna(False).astype(bool)
        if day not in frame.index or prev not in frame.index:
            continue
        for symbol in symbols:
            if symbol not in frame.columns:
                continue
            today, before = bool(frame.at[day, symbol]), bool(frame.at[prev, symbol])
            if today != before:
                rows.append({"symbol": symbol, "combo": combo, "level": lv[combo],
                             "change": CHANGE_FIRED if today else CHANGE_UNDONE})
    return pd.DataFrame(rows, columns=list(CHANGE_SCHEMA)).astype(CHANGE_SCHEMA)
