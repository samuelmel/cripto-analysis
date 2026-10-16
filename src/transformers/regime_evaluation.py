"""Avaliação da estabilidade e da qualidade dos regimes de mercado (`regimes.py`). Só descrição e diagnóstico.

Puro (CLAUDE.md §1): recebe a tabela de `classify_market_regimes` e devolve DataFrames. Não decide nada e não é
usado pelo pipeline para negociar.

Três tipos de leitura, que não se misturam:
    descrição histórica      frequência, duração, transições, trocas por ano, perfil por ano
    classificação causal     a própria tabela (cada linha usa só dados até o seu dia)
    desfecho posterior       `forward_outcomes`: o que ACONTECEU depois de cada dia classificado. Usa dados futuros em
                             relação ao dia, por construção, e serve só para avaliar o classificador depois do fato;
                             nunca entra na classificação. É exploratório: janelas de dias vizinhos se sobrepõem, então
                             o número de dias NÃO é o tamanho efetivo da amostra (use `episodes`); sem teste de
                             hipótese nem correção de múltiplas comparações (a validação estatística da Fase 3 não
                             existe neste repositório). Associação histórica, não causalidade.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

from .regimes import (
    STATUS_OK,
    TREND_STATES,
    TREND_UNDETERMINED,
    UNAVAILABLE,
    VOL_HIGH,
    VOL_NORMAL,
    RegimeRules,
    classify_market_regimes,
)

LEGACY_STATES: tuple[str, ...] = ("FAVORAVEL", "NEUTRO", "DEFENSIVO")
"""Estados do regime antigo (`selection.regime_series`), aceitos aqui só para comparar a estabilidade dos dois."""
CLASSIFIABLE: tuple[str, ...] = (*TREND_STATES, VOL_NORMAL, VOL_HIGH, *LEGACY_STATES)
"""Rótulos que descrevem o mercado (excluem INDETERMINADO e INDISPONIVEL, que são ausência de classificação)."""

MIN_EPISODES = 5
"""Menos episódios que isso num regime: amostra insuficiente para qualquer leitura (os dias vizinhos se repetem).
Atingir o mínimo (`MINIMO_ATINGIDO`) NÃO é evidência: só deixa de impedir a leitura descritiva."""

EPISODE_SCHEMA: dict[str, str] = {
    "label": "string", "start": "datetime64[ns, UTC]", "end": "datetime64[ns, UTC]", "days": "int64",
}
SUMMARY_SCHEMA: dict[str, str] = {
    "label": "string", "days": "int64", "share_pct": "float64", "episodes": "int64",
    "median_days": "float64", "mean_days": "float64", "max_days": "float64",
}


def _labels(table: pd.DataFrame, column: str) -> pd.Series:
    """Rótulos por dia; INDETERMINADO e INDISPONIVEL viram nulos (não descrevem o mercado)."""
    values = [x if isinstance(x, str) and x in CLASSIFIABLE else None for x in table[column].tolist()]
    return pd.Series(values, index=pd.DatetimeIndex(table["timestamp"]), dtype="object")


def episodes(table: pd.DataFrame, column: str) -> pd.DataFrame:
    """Sequências de dias consecutivos com o mesmo rótulo (EPISODE_SCHEMA). Um buraco (nulo) encerra o episódio."""
    labels = _labels(table, column)
    rows: list[dict[str, object]] = []
    start = prev = None
    current: str | None = None
    for ts, label in zip(pd.DatetimeIndex(labels.index), labels.tolist(), strict=True):
        if label is not None and label == current:
            prev = ts
            continue
        if current is not None and start is not None and prev is not None:
            rows.append({"label": current, "start": start, "end": prev, "days": (prev - start).days + 1})
        current, start, prev = (str(label), ts, ts) if label is not None else (None, None, None)
    if current is not None and start is not None and prev is not None:
        rows.append({"label": current, "start": start, "end": prev, "days": (prev - start).days + 1})
    return pd.DataFrame(rows, columns=list(EPISODE_SCHEMA)).astype(EPISODE_SCHEMA)


def summarize(table: pd.DataFrame, column: str) -> pd.DataFrame:
    """Frequência e duração de cada rótulo (SUMMARY_SCHEMA). `share_pct` é sobre os dias classificados."""
    labels = _labels(table, column).dropna()
    eps = episodes(table, column)
    total = len(labels)
    rows = []
    for label in pd.unique(labels):
        mine = eps.loc[eps["label"].eq(label), "days"]
        rows.append({
            "label": str(label), "days": int((labels == label).sum()),
            "share_pct": 100.0 * float((labels == label).sum()) / total if total else math.nan,
            "episodes": len(mine), "median_days": float(mine.median()), "mean_days": float(mine.mean()),
            "max_days": float(mine.max()),
        })
    return pd.DataFrame(rows, columns=list(SUMMARY_SCHEMA)).astype(SUMMARY_SCHEMA).sort_values("label", ignore_index=True)


def transition_counts(table: pd.DataFrame, column: str) -> pd.DataFrame:
    """Trocas de rótulo entre dias consecutivos classificados (from, to, count). Não conta saltos sobre buracos."""
    labels = _labels(table, column)
    prev = labels.shift(1)
    changed = labels.notna() & prev.notna() & labels.ne(prev)
    pairs = pd.DataFrame({"from": prev[changed], "to": labels[changed]})
    if pairs.empty:
        return pd.DataFrame({"from": pd.Series(dtype="string"), "to": pd.Series(dtype="string"), "count": pd.Series(dtype="int64")})
    out = pairs.groupby(["from", "to"]).size().rename("count").reset_index()
    return out.astype({"from": "string", "to": "string", "count": "int64"})


def flips_per_year(table: pd.DataFrame, column: str) -> pd.Series:
    """Número de trocas de rótulo por ano civil (índice = ano). Menos trocas = classificação mais estável."""
    labels = _labels(table, column)
    changed = labels.notna() & labels.shift(1).notna() & labels.ne(labels.shift(1))
    years = pd.DatetimeIndex(labels.index).year
    return changed.groupby(years).sum().astype("int64").rename("flips")


def agreement(a: pd.Series, b: pd.Series) -> float:
    """Fração dos dias, entre os classificados nas duas séries, em que o rótulo é igual (NaN se não há dia comum)."""
    both = a.notna() & b.notna()
    return float((a[both] == b[both]).mean()) if bool(both.any()) else math.nan


def yearly_profile(table: pd.DataFrame) -> pd.DataFrame:
    """Por ano: dias, % classificados, % de cada estado de tendência, % de volatilidade alta, trocas de tendência."""
    ts = pd.DatetimeIndex(table["timestamp"])
    trend, vol = _labels(table, "trend_regime"), _labels(table, "vol_regime")
    rows = []
    flips = flips_per_year(table, "trend_regime")
    for year in sorted(set(ts.year)):
        in_year = ts.year == year
        t, v = trend[in_year], vol[in_year]
        t_ok, v_ok = int(t.notna().sum()), int(v.notna().sum())
        row: dict[str, object] = {
            "year": int(year), "days": int(in_year.sum()),
            "classified_pct": 100.0 * t_ok / int(in_year.sum()),
            **{f"{s.lower()}_pct": (100.0 * float((t == s).sum()) / t_ok if t_ok else math.nan) for s in TREND_STATES},
            "high_vol_pct": 100.0 * float((v == VOL_HIGH).sum()) / v_ok if v_ok else math.nan,
            "trend_flips": int(flips.get(year, 0)),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def sensitivity(
    close: pd.Series, as_of: pd.Timestamp, base: RegimeRules, variants: Mapping[str, RegimeRules]
) -> pd.DataFrame:
    """Compara a classificação-base com variantes de parâmetros (mudanças moderadas): concordância de tendência e de
    volatilidade (nos dias classificados nas duas) e trocas por ano. Não escolhe parâmetros: só mede o quanto o
    resultado depende deles."""
    ref = classify_market_regimes(close, as_of, base)
    rows = []
    for name, rules in {"base": base, **variants}.items():
        alt = ref if name == "base" else classify_market_regimes(close, as_of, rules)
        rows.append({
            "variant": name,
            "trend_agreement_pct": 100.0 * agreement(_labels(ref, "trend_regime"), _labels(alt, "trend_regime")),
            "vol_agreement_pct": 100.0 * agreement(_labels(ref, "vol_regime"), _labels(alt, "vol_regime")),
            "trend_flips_per_year": float(flips_per_year(alt, "trend_regime").mean()),
            "indeterminate_days": int(alt["trend_regime"].eq(TREND_UNDETERMINED).sum()),
        })
    return pd.DataFrame(rows)


def fit_vol_threshold(vol: pd.Series, train_end: pd.Timestamp, q: float) -> float:
    """Limiar de volatilidade = quantil `q` dos valores ESTRITAMENTE anteriores a `train_end`. Nada depois entra."""
    train = vol[(vol.index < train_end) & vol.notna()]
    return float(train.quantile(q)) if len(train) else math.nan


def walk_forward_vol(table: pd.DataFrame, q: float, min_history: int) -> pd.DataFrame:
    """Walk-forward anual da volatilidade: para cada ano de teste, o limiar é ajustado só com os anos anteriores e
    congelado; compara com a classificação online (percentil contra o passado, com histerese) do mesmo ano.
    Mostra se os dois métodos contam a mesma história; o ano de teste nunca ajusta o próprio limiar."""
    idx = pd.DatetimeIndex(table["timestamp"])
    vol = pd.Series(table["vol_ann_pct"].to_numpy(dtype="float64"), index=idx)
    online = _labels(table, "vol_regime")
    rows = []
    for year in sorted(set(idx.year)):
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        in_year = idx.year == year
        if int(vol[vol.index < start].notna().sum()) < min_history:
            continue
        threshold = fit_vol_threshold(vol, start, q)
        frozen = pd.Series(
            [None if math.isnan(x) else VOL_HIGH if x > threshold else VOL_NORMAL for x in vol[in_year].tolist()],
            index=idx[in_year], dtype="object",
        )
        live = online[in_year]
        rows.append({
            "test_year": int(year), "threshold_vol_pct": threshold,
            "frozen_high_pct": 100.0 * float((frozen == VOL_HIGH).sum()) / max(int(frozen.notna().sum()), 1),
            "online_high_pct": 100.0 * float((live == VOL_HIGH).sum()) / max(int(live.notna().sum()), 1),
            "agreement_pct": 100.0 * agreement(frozen, live),
        })
    return pd.DataFrame(rows, columns=["test_year", "threshold_vol_pct", "frozen_high_pct", "online_high_pct", "agreement_pct"])


def forward_outcomes(table: pd.DataFrame, horizon: int = 30, min_episodes: int = MIN_EPISODES) -> pd.DataFrame:
    """EXPLORATÓRIO. Por regime: retorno log médio e volatilidade realizada (anualizada) nos `horizon` dias SEGUINTES,
    e o veredito de amostra. Usa dados posteriores ao dia classificado (só para avaliar depois do fato). Dias com
    janela futura incompleta ficam de fora."""
    ts = pd.DatetimeIndex(table["timestamp"])
    px = pd.Series(table["close"].to_numpy(dtype="float64"), index=ts)
    logret = pd.Series(np.log(px.to_numpy(dtype="float64")), index=ts).diff()
    fwd_ret = np.log(px.shift(-horizon) / px)
    fwd_vol = logret.rolling(horizon, min_periods=horizon).std(ddof=1).shift(-horizon) * math.sqrt(365) * 100.0
    rows = []
    for column in ("trend_regime", "vol_regime"):
        labels = _labels(table, column)
        eps = episodes(table, column)
        for label in sorted(str(x) for x in pd.unique(labels.dropna())):
            mine = labels.eq(label)
            n_eps = int(eps["label"].eq(label).sum())
            rows.append({
                "dimension": column, "label": label, "days": int(mine.sum()), "episodes": n_eps,
                "fwd_ret_mean_pct": float((np.exp(fwd_ret[mine].mean()) - 1.0) * 100.0),
                "fwd_vol_mean_pct": float(fwd_vol[mine].mean()),
                "n_with_future": int(fwd_ret[mine].notna().sum()),
                "sample": "MINIMO_ATINGIDO" if n_eps >= min_episodes else "AMOSTRA_INSUFICIENTE",
            })
    return pd.DataFrame(rows)


def validity(table: pd.DataFrame) -> pd.DataFrame:
    """Dias por status (tendência e volatilidade): quanto do período é classificável e por que o resto não é."""
    if table.empty:
        return pd.DataFrame({"dimension": pd.Series(dtype="string"), "status": pd.Series(dtype="string"), "days": pd.Series(dtype="int64")})
    frames = [
        table[col].value_counts().rename_axis("status").rename("days").reset_index().assign(dimension=dim)
        for dim, col in (("trend", "status"), ("vol", "vol_status"))
    ]
    out = pd.concat(frames, ignore_index=True)
    return out[["dimension", "status", "days"]].astype({"dimension": "string", "status": "string", "days": "int64"})


def is_available(table: pd.DataFrame) -> bool:
    """A última linha tem tendência classificada com dado confiável (status OK)?"""
    return (not table.empty) and bool(table["status"].iloc[-1] == STATUS_OK) and bool(table["trend_regime"].iloc[-1] != UNAVAILABLE)
