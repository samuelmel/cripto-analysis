"""Estudo dos regimes de mercado (Fase 4): frequência, duração, trocas, estabilidade por ano e por período,
sensibilidade a parâmetros, walk-forward da volatilidade e desfechos posteriores (exploratórios).

Uso (da raiz do projeto, com a base local montada pelo pipeline):

    uv run python research/regime_study.py

Grava data/research/regime_study.parquet (formato longo: section, key, period, metric, value, note) e imprime um
resumo. Só lê a base local e escreve esse arquivo; não altera nenhuma saída do pipeline.

O que este estudo é, e o que não é:
    - Os parâmetros do classificador estão em config.py, fixados a priori. Nada aqui os escolhe ou otimiza: a
      sensibilidade só MEDE o quanto o resultado muda com variações moderadas.
    - A classificação é causal (cada dia usa só candles fechados até ele). Os "desfechos posteriores" olham para a
      frente de propósito, só para avaliar o classificador depois do fato, e são exploratórios: janelas vizinhas se
      sobrepõem, não há teste de hipótese nem correção de múltiplas comparações (a validação estatística da Fase 3
      não existe neste repositório) e associação histórica não é causalidade.
    - Uma única história de mercado (BTC, desde 2017). Quem tem poucos episódios fica marcado AMOSTRA_INSUFICIENTE.
    - Não compara retorno de estratégias por regime: isso fica para a Fase 5, depois da validação estatística.
    - "Hoje" não vem do relógio: `as_of` é o fechamento do último candle da base, para o resultado ser reprodutível.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import REGIME_SYMBOL, TEST_PERIOD, TRAIN_PERIOD, UNIVERSE, VALIDATION_PERIOD  # noqa: E402
from src.loaders.market_store import read_ohlcv  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.regime_evaluation import (  # noqa: E402
    flips_per_year,
    forward_outcomes,
    sensitivity,
    summarize,
    transition_counts,
    validity,
    walk_forward_vol,
    yearly_profile,
)
from src.transformers.regimes import RegimeRules, classify_market_regimes  # noqa: E402
from src.transformers.selection import compute_features, regime_series  # noqa: E402
from src.transformers.strategies import market_from_candles  # noqa: E402

OUT = Path("data/research/regime_study.parquet")
SCHEMA = {"section": "string", "key": "string", "period": "string", "metric": "string", "value": "float64", "note": "string"}
PERIODS: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {
    "TREINO": (pd.Timestamp(TRAIN_PERIOD[0], tz="UTC"), pd.Timestamp(VALIDATION_PERIOD[0], tz="UTC") - pd.Timedelta(days=1)),
    "VALIDACAO": (pd.Timestamp(VALIDATION_PERIOD[0], tz="UTC"), pd.Timestamp(VALIDATION_PERIOD[1], tz="UTC")),
    "TESTE": (pd.Timestamp(TEST_PERIOD[0], tz="UTC"), pd.Timestamp(TEST_PERIOD[1], tz="UTC")),
}
NAN = float("nan")


def melt(section: str, frame: pd.DataFrame, key: str, period: str = "TODOS", note: str = "") -> list[dict[str, object]]:
    """DataFrame de resultados -> linhas longas (uma por métrica numérica)."""
    rows: list[dict[str, object]] = []
    for _, r in frame.iterrows():
        for col in frame.columns:
            value = r[col]
            if col != key and isinstance(value, int | float | np.integer | np.floating):
                rows.append({"section": section, "key": str(r[key]), "period": period, "metric": col, "value": float(value), "note": note})
    return rows


def in_period(table: pd.DataFrame, span: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    ts = pd.DatetimeIndex(table["timestamp"])
    return table[(ts >= span[0]) & (ts <= span[1])]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raw = read_ohlcv(list(UNIVERSE))
    candles = clean_candles(raw[raw["symbol"].eq(REGIME_SYMBOL)])
    if candles.empty:
        print(f"base local sem {REGIME_SYMBOL}: rode `uv run python -m src.pipeline` antes")
        return 1
    close = pd.Series(candles["close"].to_numpy(dtype="float64"), index=pd.DatetimeIndex(candles["timestamp"]))
    as_of = pd.Timestamp(close.index.max()) + pd.Timedelta(days=1)  # fechamento do último candle da base
    rules = RegimeRules()
    legacy = regime_series(compute_features(market_from_candles(clean_candles(raw))))
    table = classify_market_regimes(close, as_of, rules, legacy=legacy)

    rows: list[dict[str, object]] = []
    rows += melt("validade", validity(table).assign(key=lambda d: d["dimension"] + ":" + d["status"]), "key")
    for column, name in (("trend_regime", "tendencia"), ("vol_regime", "volatilidade"), ("legacy_regime", "legado")):
        rows += melt(f"frequencia_{name}", summarize(table, column), "label")
        for period, span in PERIODS.items():
            rows += melt(f"frequencia_{name}", summarize(in_period(table, span), column), "label", period)
    flips = pd.DataFrame({
        "year": flips_per_year(table, "trend_regime").index.astype(str),
        "trend_flips": flips_per_year(table, "trend_regime").to_numpy(dtype="float64"),
        "legacy_flips": flips_per_year(table, "legacy_regime").reindex(flips_per_year(table, "trend_regime").index).to_numpy(dtype="float64"),
        "vol_flips": flips_per_year(table, "vol_regime").reindex(flips_per_year(table, "trend_regime").index).to_numpy(dtype="float64"),
    })
    rows += melt("trocas_por_ano", flips, "year", note="trocas de rótulo entre dias consecutivos classificados")
    tc = transition_counts(table, "trend_regime")
    rows += melt("transicoes_tendencia", tc.assign(key=lambda d: d["from"] + "->" + d["to"]).drop(columns=["from", "to"]), "key")
    rows += melt("perfil_anual", yearly_profile(table), "year")
    rows += melt("cruzamento_legado", pd.crosstab(table["legacy_regime"].astype(object), table["trend_regime"].astype(object))
                 .stack().rename("days").reset_index().assign(key=lambda d: d["legacy_regime"] + "|" + d["trend_regime"])[["key", "days"]],
                 "key", note="dias por (regime antigo | regime novo)")

    variants = {
        "banda 4%": replace(rules, trend_band=0.04), "banda 6%": replace(rules, trend_band=0.06),
        "inclinação plana 1,5%": replace(rules, slope_flat=0.015), "inclinação plana 2,5%": replace(rules, slope_flat=0.025),
        "confirmação 3 dias": replace(rules, confirm_days=3), "confirmação 7 dias": replace(rules, confirm_days=7),
        "média 150": replace(rules, ma_window=150), "média 250": replace(rules, ma_window=250),
        "volatilidade 75/65": replace(rules, vol_enter=0.75, vol_exit=0.65), "volatilidade 85/75": replace(rules, vol_enter=0.85, vol_exit=0.75),
    }
    rows += melt("sensibilidade", sensitivity(close, as_of, rules, variants), "variant",
                 note="concordância com os parâmetros-base nos dias classificados nas duas versões")
    rows += melt("walk_forward_volatilidade", walk_forward_vol(table, rules.vol_enter, rules.vol_min_history), "test_year",
                 note="limiar ajustado só com anos anteriores ao ano de teste")
    outcomes = forward_outcomes(table, horizon=30)
    rows += melt("desfechos_exploratorios", outcomes.assign(key=lambda d: d["dimension"] + ":" + d["label"]), "key",
                 note="retorno/volatilidade dos 30 dias SEGUINTES; exploratório, sem inferência")

    result = pd.DataFrame(rows)[list(SCHEMA)].astype(SCHEMA)
    write_parquet(result, OUT)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.max_rows", 500)
    print(f"{REGIME_SYMBOL}: {len(table)} dias, {table['timestamp'].min():%Y-%m-%d} a {table['timestamp'].max():%Y-%m-%d}; "
          f"classificador {table['classifier_version'].iloc[0]}, params {table['params_hash'].iloc[0]}")
    print("\n=== validade ===\n" + validity(table).to_string(index=False))
    for column in ("trend_regime", "vol_regime", "legacy_regime"):
        print(f"\n=== {column} ===\n" + summarize(table, column).round(1).to_string(index=False))
    print("\n=== trocas por ano ===\n" + flips.round(0).to_string(index=False))
    print("\n=== transições de tendência ===\n" + tc.to_string(index=False))
    print("\n=== perfil por ano ===\n" + yearly_profile(table).round(1).to_string(index=False))
    print("\n=== sensibilidade ===\n" + sensitivity(close, as_of, rules, variants).round(1).to_string(index=False))
    print("\n=== walk-forward da volatilidade ===\n" + walk_forward_vol(table, rules.vol_enter, rules.vol_min_history).round(1).to_string(index=False))
    print("\n=== desfechos posteriores (EXPLORATÓRIO) ===\n" + outcomes.round(2).to_string(index=False))
    print(f"\nGravado em {OUT} ({len(result)} linhas).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
