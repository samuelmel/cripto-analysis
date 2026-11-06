"""Modelos de IA em modo sombra: especificação, walk-forward, previsão do dia, registro imutável e resultado realizado.

Puro (CLAUDE.md §1). Protocolo: docs/ml_study.md (fixado antes dos resultados).

Modelos (hiperparâmetros fixos, sem ajuste):
    F_LOGIT          regressão logística L2 (`entry_model`, λ = 1) com as 11 features do modelo F
    F_LOGIT_SEM_FNG  a mesma, sem as 2 features do Fear & Greed
    G_GBM            gradient boosting de árvores (`gbm.GBMParams` padrão) com as 11 features
    G_GBM_SEM_FNG    o mesmo, sem o Fear & Greed
Alvo e features: os de `entry_model` (supera o BTC em 30 dias, líquido, nas aberturas; features só até `t`).

Modo sombra: as previsões são calculadas e REGISTRADAS todo dia (repositório de estado, `model_predictions.parquet`) e a opinião da
IA aparece como "IA (em teste)" no Telegram e no painel. Só influenciam o aporte simulado se a trava de promoção
(`promotion_gate`, docs/promocao_ia.md) aprovar; do contrário não entram na recomendação nem no estágio. O registro tem cadeia de hash e nunca reescreve (dia, moeda,
modelo) já gravado: é o teste prospectivo. Sem Fear & Greed no dia, os modelos com F&G não preveem (ausência não vira
zero) e os SEM_FNG continuam.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .bootstrap import BootstrapConfig, bootstrap_statistic, make_resampler
from .entry_model import FEATURES, L2_LAMBDA, PURGE_DAYS, TARGET_HORIZON, fit_logistic, predict
from .entry_signals import Panel, forward_returns, universe_reference
from .gbm import GBMParams, fit_gbm, predict_gbm

KIND_LOGIT = "LOGIT"
KIND_GBM = "GBM"
FNG_FEATURES: tuple[str, ...] = ("fng", "fng_change_7")
BASE_FEATURES: tuple[str, ...] = tuple(f for f in FEATURES if f not in FNG_FEATURES)
SHADOW_TOP_K = 5   # mesmo k do modelo F no estudo dos sinais de entrada
PROTOCOL = "ml-v1"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    kind: str
    features: tuple[str, ...]

    @property
    def version(self) -> str:
        """Impressão digital do modelo: tipo, features, hiperparâmetros, alvo, expurgo e protocolo."""
        params: object = {"l2": L2_LAMBDA} if self.kind == KIND_LOGIT else asdict(GBMParams())
        text = json.dumps({"name": self.name, "kind": self.kind, "features": self.features, "params": params,
                           "horizon": TARGET_HORIZON, "purge": PURGE_DAYS, "protocol": PROTOCOL}, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("F_LOGIT", KIND_LOGIT, FEATURES),
    ModelSpec("F_LOGIT_SEM_FNG", KIND_LOGIT, BASE_FEATURES),
    ModelSpec("G_GBM", KIND_GBM, FEATURES),
    ModelSpec("G_GBM_SEM_FNG", KIND_GBM, BASE_FEATURES),
)


def stack_all(features: Mapping[str, pd.DataFrame], target: pd.DataFrame, member: pd.DataFrame) -> pd.DataFrame:
    """Linhas (dia, moeda) do universo do dia com as features-base completas; F&G e alvo podem ser NaN."""
    cols = {name: features[name].where(member).stack(future_stack=True) for name in FEATURES}
    frame = pd.DataFrame(cols)
    frame["target"] = target.where(member).stack(future_stack=True).reindex(frame.index)
    frame.index = frame.index.set_names(["timestamp", "symbol"])
    keep = member.stack(future_stack=True).reindex(frame.index).fillna(False).astype(bool)
    return frame[keep & frame[list(BASE_FEATURES)].notna().all(axis=1)]


def usable(rows: pd.DataFrame, spec: ModelSpec) -> pd.DataFrame:
    """As linhas com todas as features do modelo (sem imputação)."""
    return rows[rows[list(spec.features)].notna().all(axis=1)]


def fit_predict(spec: ModelSpec, train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Ajusta no treino e prevê o teste (padronização e faixas só do treino)."""
    x = train[list(spec.features)].to_numpy("float64")
    y = train["target"].to_numpy("float64")
    xt = test[list(spec.features)].to_numpy("float64")
    if spec.kind == KIND_LOGIT:
        return predict(fit_logistic(x, y, L2_LAMBDA), xt)
    if spec.kind == KIND_GBM:
        return predict_gbm(fit_gbm(x, y, GBMParams()), xt)
    raise ValueError(f"tipo de modelo desconhecido: {spec.kind}")


FOLD_SCHEMA: dict[str, str] = {
    "model": "string", "year": "int64", "train_end": "datetime64[ns, UTC]", "n_train": "int64", "n_test": "int64",
    "positive_rate": "float64",
}


def walk_forward(spec: ModelSpec, rows: pd.DataFrame, years: Sequence[int], purge_days: int = PURGE_DAYS) -> tuple[pd.Series, pd.DataFrame]:
    """Probabilidade fora da amostra por (dia, moeda) nos anos `years`. Dobra Y: treino com dias <= 31/12 de Y−1 menos
    o expurgo e alvo conhecido; teste = dias de Y. Mesma regra do modelo F (`entry_model.walk_forward`)."""
    data = usable(rows, spec)
    days = pd.DatetimeIndex(data.index.get_level_values("timestamp"))
    preds: list[pd.Series] = []
    folds: list[dict[str, object]] = []
    for year in years:
        train_end = pd.Timestamp(f"{year - 1}-12-31", tz="UTC") - pd.Timedelta(days=purge_days)
        train = data[(days <= train_end) & data["target"].notna().to_numpy()]
        test = data[days.year == year]
        if train.empty or test.empty or train["target"].nunique() < 2:
            continue
        preds.append(pd.Series(fit_predict(spec, train, test), index=test.index, name="prob"))
        folds.append({"model": spec.name, "year": year, "train_end": train_end, "n_train": len(train), "n_test": len(test),
                      "positive_rate": float(train["target"].mean())})
    prob = pd.concat(preds) if preds else pd.Series(dtype="float64", name="prob")
    return prob, pd.DataFrame(folds, columns=list(FOLD_SCHEMA)).astype(FOLD_SCHEMA)


# ---------------------------------------------------------------------------------------------
# Previsão do dia e registro imutável
# ---------------------------------------------------------------------------------------------

GENESIS = "0" * 64
PREDICTION_LOG_SCHEMA: dict[str, str] = {
    "day": "datetime64[ns, UTC]",        # dia do último candle usado (a previsão vale para a entrada em day+1)
    "symbol": "string",
    "model": "string",
    "model_version": "string",
    "prob": "float64",                   # probabilidade prevista de superar o BTC em 30 dias
    "rank": "Int64",                     # 1 = maior probabilidade do dia entre as moedas do universo
    "in_top_k": "bool",
    "n_universe": "Int64",
    "n_train": "Int64",
    "train_end": "datetime64[ns, UTC]",  # último dia de sinal no treino (day − expurgo)
    "run_ts": "datetime64[ns, UTC]",
    "data_fingerprint": "string",
    "code_version": "string",
    "prev_hash": "string",
    "row_hash": "string",
}
_PAYLOAD = tuple(c for c in PREDICTION_LOG_SCHEMA if c not in ("prev_hash", "row_hash"))
_KEY = ("day", "symbol", "model")


def empty_log() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in PREDICTION_LOG_SCHEMA.items()})


def live_predictions(
    rows: pd.DataFrame,
    day: pd.Timestamp,
    *,
    run_ts: pd.Timestamp,
    data_fingerprint: str,
    code_version: str,
    specs: Sequence[ModelSpec] = MODELS,
    top_k: int = SHADOW_TOP_K,
    purge_days: int = PURGE_DAYS,
) -> tuple[pd.DataFrame, list[str]]:
    """(linhas do registro para `day`, notas). Cada modelo treina com as linhas de alvo conhecido até `day − expurgo`
    (todo alvo de treino termina antes de `day`) e prevê as moedas do universo de `day`. Sem features completas no dia
    (ex.: Fear & Greed ausente), o modelo não prevê e a nota diz por quê."""
    out: list[pd.DataFrame] = []
    notes: list[str] = []
    train_end = day - pd.Timedelta(days=purge_days)
    for spec in specs:
        data = usable(rows, spec)
        days = pd.DatetimeIndex(data.index.get_level_values("timestamp"))
        train = data[(days <= train_end) & data["target"].notna().to_numpy()]
        today = data[days == day]
        if today.empty:
            needs_fng = any(f in FNG_FEATURES for f in spec.features)
            has_base = bool((days_of(rows) == day).any())
            reason = "Fear & Greed ausente" if needs_fng and has_base else "sem moedas com features completas"
            notes.append(f"{spec.name}: sem previsão em {day:%Y-%m-%d} ({reason})")
            continue
        if train.empty or train["target"].nunique() < 2:
            notes.append(f"{spec.name}: treino insuficiente até {train_end:%Y-%m-%d}")
            continue
        prob = fit_predict(spec, train, today)
        symbols = today.index.get_level_values("symbol").astype(str)
        rank = pd.Series(prob).rank(ascending=False, method="first").astype("int64").to_numpy()
        out.append(pd.DataFrame({
            "day": day, "symbol": symbols, "model": spec.name, "model_version": spec.version, "prob": prob,
            "rank": rank, "in_top_k": rank <= top_k, "n_universe": len(today), "n_train": len(train), "train_end": train_end,
            "run_ts": run_ts, "data_fingerprint": data_fingerprint, "code_version": code_version,
        }))
    if not out:
        return empty_log().drop(columns=["prev_hash", "row_hash"]), notes
    frame = pd.concat(out, ignore_index=True)
    return frame.astype({c: t for c, t in PREDICTION_LOG_SCHEMA.items() if c in frame.columns}), notes


def days_of(rows: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(rows.index.get_level_values("timestamp"))


def _cell(value: object) -> str:
    if value is None or value is pd.NA or value is pd.NaT or (isinstance(value, float) and np.isnan(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float | np.floating):
        return f"{float(value):.12g}"
    return str(value)


def row_hash(prev_hash: str, row: Mapping[Hashable, object]) -> str:
    payload = "|".join(_cell(row[c]) for c in _PAYLOAD)
    return hashlib.sha256(f"{prev_hash}|{payload}".encode("utf-8")).hexdigest()


def chain_rows(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Só as linhas novas (dia, moeda, modelo ainda ausentes), encadeadas a partir do último hash."""
    seen = set(zip(*(existing[k] for k in _KEY), strict=True)) if not existing.empty else set()
    fresh = new[[key not in seen for key in zip(*(new[k] for k in _KEY), strict=True)]]
    fresh = fresh.sort_values(list(_KEY), ignore_index=True)
    prev = str(existing["row_hash"].iloc[-1]) if not existing.empty else GENESIS
    previous, hashes = [], []
    for row in fresh.to_dict("records"):
        previous.append(prev)
        prev = row_hash(prev, row)
        hashes.append(prev)
    return fresh.assign(prev_hash=previous, row_hash=hashes)[list(PREDICTION_LOG_SCHEMA)].astype(PREDICTION_LOG_SCHEMA)


def verify_chain(log: pd.DataFrame) -> list[str]:
    """Problemas da cadeia (vazia = íntegra)."""
    problems: list[str] = []
    prev = GENESIS
    for i, row in enumerate(log.to_dict("records")):
        if str(row["prev_hash"]) != prev:
            problems.append(f"linha {i}: elo quebrado")
        if row_hash(str(row["prev_hash"]), row) != str(row["row_hash"]):
            problems.append(f"linha {i}: conteúdo alterado")
        prev = str(row["row_hash"])
    if log.duplicated(list(_KEY)).any():
        problems.append("(dia, moeda, modelo) repetido")
    return problems[:20]


OUTCOME_SCHEMA: dict[str, str] = {
    "model": "string", "day": "datetime64[ns, UTC]", "symbol": "string", "prob": "float64", "in_top_k": "bool",
    "target": "float64", "forward_30": "float64", "universe_30": "float64",
}


def realized_outcomes(log: pd.DataFrame, panel: Panel, horizon: int = TARGET_HORIZON) -> pd.DataFrame:
    """Previsões já maduras (a janela de 30 dias terminou) com o que aconteceu: alvo realizado, retorno líquido da moeda e
    média do universo no mesmo intervalo. Previsões ainda abertas ficam de fora."""
    if log.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in OUTCOME_SCHEMA.items()})
    fwd = forward_returns(panel, horizon)
    ref = universe_reference(fwd, panel.member)
    if "BTC/USDT" not in fwd.columns:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in OUTCOME_SCHEMA.items()})
    beat = fwd.gt(fwd["BTC/USDT"], axis=0).astype("float64").where(fwd.notna() & fwd["BTC/USDT"].notna().to_numpy()[:, None])
    key = pd.MultiIndex.from_arrays([pd.DatetimeIndex(log["day"]), log["symbol"].astype(str)])
    out = pd.DataFrame({
        "model": log["model"].to_numpy(), "day": log["day"].to_numpy(), "symbol": log["symbol"].to_numpy(),
        "prob": log["prob"].to_numpy(), "in_top_k": log["in_top_k"].to_numpy(),
        "target": beat.stack(future_stack=True).reindex(key).to_numpy(),
        "forward_30": fwd.stack(future_stack=True).reindex(key).to_numpy(),
        "universe_30": ref.reindex(pd.DatetimeIndex(log["day"])).to_numpy(),
    })
    out = out.dropna(subset=["target", "forward_30", "universe_30"])
    return out.astype(OUTCOME_SCHEMA).reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# Histórico do Fear & Greed (cópia diária no repositório de estado)
# ---------------------------------------------------------------------------------------------

FNG_HISTORY_SCHEMA: dict[str, str] = {
    "timestamp": "datetime64[ns, UTC]",
    "fng_value": "Int64",
    "fng_classification": "string",
    "first_seen": "datetime64[ns, UTC]",   # execução que viu esse valor pela primeira vez
}


def new_fng_rows(history: pd.DataFrame, fresh: pd.DataFrame, seen_at: pd.Timestamp) -> pd.DataFrame:
    """Leituras (dia, valor) ainda não guardadas. Um dia cujo valor mudou na fonte entra de novo (revisão auditável);
    nada é apagado."""
    if fresh.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in FNG_HISTORY_SCHEMA.items()})
    f = pd.DataFrame({
        "timestamp": pd.to_datetime(fresh["timestamp"], utc=True).dt.floor("D"),
        "fng_value": pd.to_numeric(fresh["fng_value"], errors="coerce").astype("Int64"),
        "fng_classification": fresh["fng_classification"].astype("string"),
    }).dropna(subset=["timestamp", "fng_value"]).drop_duplicates(["timestamp", "fng_value"])
    if not history.empty:
        known = set(zip(history["timestamp"], history["fng_value"].astype("int64"), strict=True))
        f = f[[(t, int(v)) not in known for t, v in zip(f["timestamp"], f["fng_value"], strict=True)]]
    return f.assign(first_seen=seen_at).sort_values("timestamp", ignore_index=True).astype(FNG_HISTORY_SCHEMA)


def latest_fng(history: pd.DataFrame) -> pd.DataFrame:
    """O histórico no formato de `read_fng` (timestamp, symbol, fng_value, fng_classification), com o valor mais recente
    visto para cada dia."""
    if history.empty:
        return pd.DataFrame()
    last = history.sort_values(["timestamp", "first_seen"]).drop_duplicates("timestamp", keep="last")
    return pd.DataFrame({"timestamp": last["timestamp"], "symbol": "MARKET", "fng_value": last["fng_value"],
                         "fng_classification": last["fng_classification"]}).reset_index(drop=True)


def fng_series(fng: pd.DataFrame) -> pd.Series | None:
    """Série diária do índice (float) a partir do formato de `read_fng`; None se vazio."""
    if fng.empty:
        return None
    s = fng.assign(timestamp=pd.to_datetime(fng["timestamp"], utc=True).dt.floor("D")).drop_duplicates("timestamp", keep="last")
    return s.set_index("timestamp")["fng_value"].astype("float64")


# ---------------------------------------------------------------------------------------------
# Trava de promoção da IA (docs/promocao_ia.md, `promotion-gate-v1`: critério fixado antes de qualquer avaliação)
# ---------------------------------------------------------------------------------------------

GATE_ID = "promotion-gate-v1"
GATE_MIN_DAYS = 90        # dias de previsões ao vivo já maduras
GATE_CI_LEVEL = 0.90
GATE_RESAMPLES = 2000
GATE_SEED = 20261105
GATE_BLOCK_DAYS = 30.0    # as janelas de 30 dias se sobrepõem
AI_MODEL = "G_GBM"
AI_FALLBACK_MODEL = "G_GBM_SEM_FNG"
AI_LABEL = "IA (em teste)"

GATE_APPROVED = "APROVADA"
GATE_REJECTED = "REPROVADA"
GATE_FEW_DAYS = "DADOS_INSUFICIENTES"
GATE_BAD_CHAIN = "CADEIA_INVALIDA"


@dataclass(frozen=True)
class GateResult:
    status: str
    n_days: int
    min_days: int
    mean_excess: float        # fração (0,01 = 1 ponto percentual)
    ci_low: float
    ci_high: float
    problems: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.status == GATE_APPROVED


def ai_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Linhas da IA: por dia vale o `G_GBM`; se ele não previu nesse dia, o `G_GBM_SEM_FNG` (sem escolher modelo depois)."""
    if frame.empty:
        return frame
    main = frame[frame["model"].astype(str).eq(AI_MODEL)]
    fallback = frame[frame["model"].astype(str).eq(AI_FALLBACK_MODEL) & ~frame["day"].isin(main["day"])]
    return pd.concat([main, fallback], ignore_index=True)


def daily_excess(outcomes: pd.DataFrame) -> pd.Series:
    """Por dia maduro: média do retorno líquido de 30 dias das escolhas da IA (top k) menos a média do universo."""
    rows = ai_rows(outcomes)
    if rows.empty:
        return pd.Series(dtype="float64")
    top = rows[rows["in_top_k"].astype(bool)]
    grouped = top.groupby("day")
    return (grouped["forward_30"].mean() - grouped["universe_30"].first()).dropna().sort_index().astype("float64")


def promotion_gate(
    log: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    min_days: int = GATE_MIN_DAYS,
    n_boot: int = GATE_RESAMPLES,
    seed: int = GATE_SEED,
) -> GateResult:
    """Aprova a IA só se TODAS as condições valem: cadeia de hash íntegra, pelo menos `min_days` dias de previsões ao vivo
    já maduras e excesso médio das escolhas sobre o universo, líquido de custos, com o limite inferior do IC de 90% > 0.

    `log`: registro de previsões (PREDICTION_LOG_SCHEMA). `outcomes`: `realized_outcomes(log, panel)`, só previsões maduras.
    Só olha previsões ao vivo do registro (nunca o walk-forward do estudo). Pura e determinística."""
    problems = tuple(verify_chain(log)) if not log.empty else ()
    excess = daily_excess(outcomes)
    n = int(excess.size)
    nan = float("nan")
    if problems:
        return GateResult(GATE_BAD_CHAIN, n, min_days, nan, nan, nan, problems)
    if n < min_days:
        mean = float(excess.mean()) if n else nan
        return GateResult(GATE_FEW_DAYS, n, min_days, mean, nan, nan)
    x = excess.to_numpy(dtype="float64")
    cfg = BootstrapConfig(n_boot=n_boot, seed=seed, ci_level=GATE_CI_LEVEL, block=GATE_BLOCK_DAYS)
    estimate = bootstrap_statistic(x, lambda m: np.asarray(m.mean(axis=1), dtype="float64"), make_resampler([x], cfg))
    ok = estimate.estimate > 0.0 and estimate.ci_low > 0.0
    return GateResult(GATE_APPROVED if ok else GATE_REJECTED, n, min_days, estimate.estimate, estimate.ci_low, estimate.ci_high)


def ai_picks_today(today: pd.DataFrame, top_k: int = SHADOW_TOP_K) -> list[str]:
    """Moedas que a IA escolhe hoje (as `top_k` de maior probabilidade do dia), na ordem do ranking."""
    rows = ai_rows(today)
    if rows.empty:
        return []
    latest = rows[rows["day"].eq(rows["day"].max())].sort_values("rank")
    return [str(s) for s in latest["symbol"].head(top_k)]


def apply_ai_selection(assessed: pd.DataFrame, picks: Sequence[str], *, regime: str, regime_filter: str,
                       max_candidates: int) -> pd.DataFrame:
    """Com a trava aprovada, as moedas do aporte simulado passam a ser as da IA (na ordem dela), no lugar da seleção por
    score. Mantém os filtros duros: moeda EVITAR (dado, liquidez, volatilidade, queda, tendência de baixa, bloqueio manual) e
    mercado defensivo com filtro de bloqueio nunca entram. Valor e dimensionamento seguem `allocate`. Nunca envia ordem."""
    out = assessed.copy()
    blocked_market = regime == "DEFENSIVO" and regime_filter == "bloquear"
    ok = {str(r.symbol) for r in out.itertuples() if str(r.opportunity) != "EVITAR"}
    chosen = [] if blocked_market else [s for s in picks if s in ok][:max_candidates]
    rank = {s: i + 1 for i, s in enumerate(chosen)}
    out["selected"] = out["symbol"].astype(str).isin(rank)
    out["candidate_rank"] = pd.array([rank.get(str(s)) for s in out["symbol"]], dtype="Int64")
    take = out["selected"]
    out.loc[take & ~out["opportunity"].astype(str).isin(["BOA_RELATIVA", "MODERADA"]), "opportunity"] = "MODERADA"
    reasons = [[f"escolhida pela {AI_LABEL}, aprovada na trava de promoção", *list(r)] if t else list(r)
               for r, t in zip(out["reasons"], take, strict=True)]
    out["reasons"] = pd.Series(reasons, index=out.index, dtype="object")
    return out.sort_values(["candidate_rank", "symbol"], na_position="last", ignore_index=True)


AI_STATUS_SCHEMA: dict[str, str] = {
    "model": "string", "label": "string", "status": "string", "approved": "bool", "n_days": "int64", "min_days": "int64",
    "mean_excess_pp": "float64", "ci_low_pp": "float64", "ci_high_pp": "float64", "picks": "string", "message": "string",
    "criterion": "string",
}


def gate_message(gate: GateResult) -> str:
    """Uma linha em português simples com o estado da IA."""
    if gate.status == GATE_APPROVED:
        return f"{AI_LABEL}: aprovada na trava, ela escolhe as moedas do aporte simulado."
    if gate.status == GATE_REJECTED:
        return f"{AI_LABEL}: só opina, não superou o acaso em {gate.n_days} dias avaliados."
    if gate.status == GATE_BAD_CHAIN:
        return f"{AI_LABEL}: só opina, o registro de previsões tem problema."
    return f"{AI_LABEL}: só opina, ainda sem prova ({gate.n_days} de {gate.min_days} dias avaliados)."


def ai_status_table(gate: GateResult, picks: Sequence[str]) -> pd.DataFrame:
    """Uma linha para o painel e o Telegram (AI_STATUS_SCHEMA): estado da trava e opinião do dia."""
    row = {
        "model": AI_MODEL, "label": AI_LABEL, "status": gate.status, "approved": gate.approved, "n_days": gate.n_days,
        "min_days": gate.min_days, "mean_excess_pp": gate.mean_excess * 100.0, "ci_low_pp": gate.ci_low * 100.0,
        "ci_high_pp": gate.ci_high * 100.0, "picks": ", ".join(s.split("/")[0] for s in picks),
        "message": gate_message(gate), "criterion": GATE_ID,
    }
    return pd.DataFrame([row], columns=list(AI_STATUS_SCHEMA)).astype(AI_STATUS_SCHEMA)
