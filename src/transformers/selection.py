"""Seleção de oportunidades: avalia todas as moedas do universo e diz quais merecem um aporte e por quê.

Puro (CLAUDE.md §1): recebe preços em formato largo e regras; devolve DataFrames. A mesma função (`assess`)
classifica o dia de hoje no pipeline e cada dia do backtest (`selection_backtest.py`), então o que o painel e o
Telegram mostram é exatamente o que foi testado.

Etapas (todas sobre dados até o fechamento do dia avaliado, sem olhar para frente):

1. Indicadores (`compute_features`), por moeda e dia:
     tendência        preço contra SMA 200 e SMA 50
     momento          retornos de 7, 30 e 90 dias; o score usa só 30 e 90 dias divididos pela volatilidade
                      (7 dias é ruído e só é mostrado)
     força relativa   retorno de 90 dias menos o do BTC e o do ETH (mostrado; ver pesos)
     volatilidade     desvio dos retornos log de 90 dias, anualizado (365 dias)
     queda            distância do topo de 180 dias, há quantos dias foi o topo, pior queda dos 180 dias
     liquidez         volume médio de 30 dias (USDT); spread estimado por faixa de volume (config.SPREAD_TIERS)
     persistência     % dos últimos 50 dias acima da SMA 200
     extensão         distância acima da SMA 50 em unidades da oscilação típica de 50 dias; RSI de 14 dias
     qualidade        candles reais no histórico e dias faltando nos últimos 365
     condições        estado das estratégias habilitadas (SMA 200, cruzamento de EMAs, Donchian, momento, ...)

2. Score (0 a 100): soma ponderada (config.SCORE_WEIGHTS) de quatro componentes, cada um o percentil da moeda
   entre as moedas pontuáveis do dia. Percentil = escala comum, sem que um indicador domine por ter números
   maiores; um componente por tipo de informação para não contar o mesmo movimento várias vezes. O score é
   RELATIVO: diz quem está melhor que as alternativas, não a chance de lucro (não foi calibrado para isso).

3. Classificação, na ordem (a primeira que se aplica):
     EVITAR        algum filtro obrigatório falhou: dado indisponível ou histórico curto/incompleto, liquidez
                   baixa, volatilidade ou queda excessiva, tendência de baixa (abaixo da SMA 200), bloqueio manual
     AGUARDAR      filtros ok, mas a entrada não se justifica agora: mercado defensivo (com REGIME_FILTER =
                   "bloquear"), momento de 90 dias negativo, poucas condições favoráveis, preço esticado,
                   sobrecomprado ou score abaixo de SCORE_MODERATE
     BOA_RELATIVA  score >= SCORE_STRONG e nenhum alerta de risco
     MODERADA      o resto (sinais favoráveis, mas com alerta de risco ou score intermediário)
   Nenhum indicador isolado (RSI baixo, alta recente, queda brusca, volume) leva a uma compra: entrar exige
   passar por todos os filtros ao mesmo tempo.

4. Seleção: as melhores BOA/MODERADA (até config.MAX_CANDIDATES) ficam `selected`; o aporte de cada uma é de
   `allocation.py`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config
from . import costs
from .strategies import Market, daily, donchian_breakout, ema_cross, pullback_in_uptrend, rsi, volume_breakout

OPP_STRONG = "BOA_RELATIVA"
OPP_MODERATE = "MODERADA"
OPP_WAIT = "AGUARDAR"
OPP_AVOID = "EVITAR"
OPPORTUNITIES: tuple[str, ...] = (OPP_STRONG, OPP_MODERATE, OPP_WAIT, OPP_AVOID)

REGIME_FAVORABLE = "FAVORAVEL"
REGIME_NEUTRAL = "NEUTRO"
REGIME_DEFENSIVE = "DEFENSIVO"
REGIME_UNAVAILABLE = "INDISPONIVEL"

FILTER_BLOCK = "bloquear"
FILTER_REDUCE = "reduzir"
FILTER_OFF = "desligado"

SETUPS: tuple[str, ...] = ("sma200", "ema_cross", "donchian", "momentum", "volume_breakout", "pullback")
SETUP_TEXT: dict[str, str] = {
    "sma200": "acima da média de 200 dias",
    "ema_cross": "média curta acima da longa",
    "donchian": "rompeu a máxima recente",
    "momentum": "subiu em 90 dias",
    "volume_breakout": "rompimento com volume",
    "pullback": "recuo dentro da alta",
}

VOL_WINDOW = 90
STABILITY_WINDOW = 50
DRAWDOWN_WINDOW = 180
VOLUME_DAYS = 30
FILL_LIMIT = 5  # dias sem candle no meio do histórico: preço repetido nos indicadores (o dia em si não é avaliado)
DAYS_PER_YEAR = 365

FEATURE_SCHEMA: dict[str, str] = {
    "has_candle": "bool",
    "close": "float64",
    "sma_50": "float64",
    "sma_200": "float64",
    "history_days": "Int64",
    "gap_days_365": "Int64",
    "avg_volume_30d_usd": "float64",
    "ret_7d_pct": "float64",
    "ret_30d_pct": "float64",
    "ret_90d_pct": "float64",
    "rel_btc_90d_pct": "float64",
    "rel_eth_90d_pct": "float64",
    "momentum": "float64",
    "vol_90d_pct": "float64",
    "drawdown_now_pct": "float64",
    "drawdown_days": "Int64",
    "max_drawdown_180d_pct": "float64",
    "stability_50d_pct": "float64",
    "stretch_50": "float64",
    "rsi_14_sel": "float64",
    "cost_per_side": "float64",
    **{f"setup_{s}": "bool" for s in SETUPS},
}

SELECTION_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "history_days": "Int64",
    "gap_days_365": "Int64",
    "avg_volume_30d_usd": "float64",
    "ret_7d_pct": "float64",
    "ret_30d_pct": "float64",
    "ret_90d_pct": "float64",
    "rel_btc_90d_pct": "float64",
    "rel_eth_90d_pct": "float64",
    "vol_90d_pct": "float64",
    "drawdown_now_pct": "float64",
    "drawdown_days": "Int64",
    "max_drawdown_180d_pct": "float64",
    "sma_50": "float64",
    "stretch_50": "float64",
    "stability_50d_pct": "float64",
    "conditions_met": "Int64",
    "conditions_total": "Int64",
    "conditions": "object",       # lista de str: as condições favoráveis atendidas
    "score": "float64",
    "score_momentum": "float64",
    "score_stability": "float64",
    "score_risk": "float64",
    "score_liquidity": "float64",
    "est_cost_pct": "float64",    # custo estimado de ida e volta (taxa + spread + slippage), em %
    "opportunity": "string",
    "candidate_rank": "Int64",    # 1 = melhor candidata; nulo para quem não é BOA/MODERADA
    "selected": "bool",
    "reasons": "object",          # lista de str: evidência a favor
    "risks": "object",            # lista de str: alertas de risco
    "blockers": "object",         # lista de str: o que impede a compra (EVITAR/AGUARDAR)
}


@dataclass(frozen=True)
class SelectionRules:
    regime_symbol: str = config.REGIME_SYMBOL
    max_candidates: int = config.MAX_CANDIDATES
    min_volume_usd: float = config.MIN_BUY_VOLUME_USD
    min_history_days: int = config.MIN_SCORE_HISTORY_DAYS
    max_gap_days: int = config.MAX_GAP_DAYS_365
    weights: Mapping[str, float] = field(default_factory=lambda: dict(config.SCORE_WEIGHTS))
    score_strong: float = config.SCORE_STRONG
    score_moderate: float = config.SCORE_MODERATE
    min_conditions: int = config.MIN_CONDITIONS
    setups: tuple[str, ...] = config.ENABLED_SETUPS
    setup_params: Mapping[str, Mapping[str, float]] = field(default_factory=lambda: dict(config.SETUP_PARAMS))
    max_volatility: float = config.MAX_VOLATILITY
    high_volatility: float = config.HIGH_VOLATILITY
    max_drawdown: float = config.MAX_DRAWDOWN_180D
    max_stretch: float = config.MAX_STRETCH
    max_rsi: float = config.MAX_RSI_ENTRY
    regime_filter: str = config.REGIME_FILTER
    blocklist: Mapping[str, str] = field(default_factory=lambda: dict(config.BUY_BLOCKLIST))
    fee_per_side: float = config.FEE_PER_SIDE
    spread_tiers: tuple[tuple[float, float], ...] = config.SPREAD_TIERS
    slippage: float = config.SLIPPAGE

    def __post_init__(self) -> None:
        unknown = [s for s in self.setups if s not in SETUPS]
        if unknown:
            raise ValueError(f"estratégias desconhecidas em ENABLED_SETUPS: {unknown}")
        if set(self.weights) != {"momentum", "stability", "risk", "liquidity"}:
            raise ValueError("SCORE_WEIGHTS precisa de momentum, stability, risk e liquidity")
        if any(w < 0 for w in self.weights.values()) or not math.isclose(sum(self.weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("SCORE_WEIGHTS precisa ter pesos >= 0 somando 1")
        if self.regime_filter not in (FILTER_BLOCK, FILTER_REDUCE, FILTER_OFF):
            raise ValueError(f"REGIME_FILTER inválido: {self.regime_filter!r}")
        if not 0 <= self.score_moderate <= self.score_strong <= 100:
            raise ValueError("precisa 0 <= SCORE_MODERATE <= SCORE_STRONG <= 100")

    @property
    def cost_model(self) -> costs.CostModel:
        return costs.CostModel(fee_rate=self.fee_per_side, slippage=self.slippage, spread_tiers=self.spread_tiers)


# ---------------------------------------------------------------------------------------------
# 1. Indicadores
# ---------------------------------------------------------------------------------------------

def _param(rules: SelectionRules, setup: str, key: str) -> float:
    return float(rules.setup_params[setup][key])


def cost_per_side(avg_volume: pd.DataFrame, rules: SelectionRules) -> pd.DataFrame:
    """Taxa + meia-largura do spread estimado pela faixa de volume + slippage, por lado (fração). Mesmo modelo de
    custos do motor de backtest (`costs.py`)."""
    return costs.cost_per_side(avg_volume, rules.cost_model)


def compute_features(market: Market, rules: SelectionRules = SelectionRules()) -> pd.DataFrame:
    """Indicadores de todas as moedas em todos os dias: índice (timestamp, symbol), colunas de FEATURE_SCHEMA."""
    m = daily(market)
    raw = m.close.where(m.close.gt(0))
    if raw.empty:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in FEATURE_SCHEMA.items()},
                            index=pd.MultiIndex.from_arrays([pd.DatetimeIndex([], tz="UTC"), pd.Index([], dtype="string")],
                                                            names=["timestamp", "symbol"]))
    interior = raw.bfill().notna()  # só preenche lacunas com candle depois (nunca estende um dado velho)
    close = raw.ffill(limit=FILL_LIMIT).where(interior)
    high = m.high.where(raw.notna(), close)
    low = m.low.where(raw.notna(), close)
    has_candle = raw.notna()

    logret = close.transform(np.log).diff()
    vol_d = logret.rolling(VOL_WINDOW, min_periods=VOL_WINDOW - 10).std()
    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()

    def ret(n: int) -> pd.DataFrame:
        return close / close.shift(n) - 1.0

    r7, r30, r90 = ret(7), ret(30), ret(90)
    m30 = r30.transform(np.log1p) / (vol_d * math.sqrt(30))
    m90 = r90.transform(np.log1p) / (vol_d * math.sqrt(90))
    above = close.gt(sma200).astype(float).where(sma200.notna())
    peak = close.rolling(DRAWDOWN_WINDOW, min_periods=30).max()
    dd_now = close / peak - 1.0
    dd_days = close.rolling(DRAWDOWN_WINDOW, min_periods=30).apply(
        lambda x: float(len(x) - 1 - np.nanargmax(x)) if np.isfinite(x).any() else np.nan, raw=True
    )
    avg_volume = m.volume.rolling(VOLUME_DAYS, min_periods=20).mean()
    listed = has_candle.cummax()

    def relative(symbol: str) -> pd.DataFrame:
        if symbol not in r90.columns:
            return pd.DataFrame(np.nan, index=r90.index, columns=r90.columns)
        return r90.sub(r90[symbol], axis=0) * 100.0

    filled = Market(close, high, low, m.volume)
    setups: dict[str, pd.DataFrame] = {
        "sma200": close.gt(sma200).astype(float),
        "ema_cross": ema_cross(close, int(_param(rules, "ema_cross", "fast")), int(_param(rules, "ema_cross", "slow"))),
        "donchian": donchian_breakout(filled, int(_param(rules, "donchian", "n"))),
        "momentum": ret(int(_param(rules, "momentum", "days"))).gt(0).astype(float),
        "volume_breakout": volume_breakout(filled, int(_param(rules, "volume_breakout", "n")), _param(rules, "volume_breakout", "k")),
        "pullback": pullback_in_uptrend(close, sma50, sma200, _param(rules, "pullback", "enter_z")),
    }

    wide: dict[str, pd.DataFrame] = {
        "has_candle": has_candle.astype(float),
        "close": close,
        "sma_50": sma50,
        "sma_200": sma200,
        "history_days": has_candle.cumsum().astype(float),
        "gap_days_365": (~has_candle & listed).astype(float).rolling(DAYS_PER_YEAR, min_periods=1).sum(),
        "avg_volume_30d_usd": avg_volume,
        "ret_7d_pct": r7 * 100.0,
        "ret_30d_pct": r30 * 100.0,
        "ret_90d_pct": r90 * 100.0,
        "rel_btc_90d_pct": relative(rules.regime_symbol),
        "rel_eth_90d_pct": relative("ETH/USDT"),
        "momentum": (m30 + m90) / 2.0,
        "vol_90d_pct": vol_d * math.sqrt(DAYS_PER_YEAR) * 100.0,
        "drawdown_now_pct": dd_now * 100.0,
        "drawdown_days": dd_days,
        "max_drawdown_180d_pct": dd_now.rolling(DRAWDOWN_WINDOW, min_periods=30).min() * 100.0,
        "stability_50d_pct": above.rolling(STABILITY_WINDOW, min_periods=STABILITY_WINDOW).mean() * 100.0,
        "stretch_50": (close / sma50).transform(np.log) / (vol_d * math.sqrt(50)),
        "rsi_14_sel": rsi(close),
        "cost_per_side": cost_per_side(avg_volume, rules),
        **{f"setup_{name}": frame for name, frame in setups.items()},
    }
    panel = pd.DataFrame(pd.concat(wide, axis=1).stack(level=1, future_stack=True))
    panel.index = panel.index.set_names(["timestamp", "symbol"])
    panel = panel[panel["history_days"].gt(0)]  # antes da listagem a moeda não existe
    out = panel.replace([np.inf, -np.inf], np.nan)
    for col in ("has_candle", *(f"setup_{s}" for s in SETUPS)):
        out[col] = out[col].fillna(0.0).gt(0)
    out = out[list(FEATURE_SCHEMA)].astype(FEATURE_SCHEMA)
    return out


def regime_series(features: pd.DataFrame, regime_symbol: str = config.REGIME_SYMBOL) -> pd.Series:
    """Estado do mercado em cada dia pelo BTC: DEFENSIVO (abaixo da SMA 200), FAVORAVEL (acima e com a SMA 50
    acima da SMA 200), NEUTRO (acima, mas com a média curta abaixo da longa) ou INDISPONIVEL."""
    days = features.index.get_level_values("timestamp").unique()
    if regime_symbol not in set(features.index.get_level_values("symbol")):
        return pd.Series(REGIME_UNAVAILABLE, index=days, dtype="string")
    btc = features.xs(regime_symbol, level="symbol").reindex(days)
    ok = btc["has_candle"].fillna(False).astype(bool) & btc["sma_200"].notna() & btc["sma_50"].notna()
    out = np.select(
        [~ok, btc["close"].lt(btc["sma_200"]), btc["sma_50"].gt(btc["sma_200"])],
        [REGIME_UNAVAILABLE, REGIME_DEFENSIVE, REGIME_FAVORABLE],
        REGIME_NEUTRAL,
    )
    return pd.Series(out, index=days, dtype="string")


# ---------------------------------------------------------------------------------------------
# 2–4. Score, classificação e seleção de um dia
# ---------------------------------------------------------------------------------------------

def _num(x: float, digits: int = 1) -> str:
    return f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x: float, digits: int = 1) -> str:
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{_num(abs(x), digits)}%"


def _musd(x: float) -> str:
    return f"US$ {_num(x / 1e6, 0 if x >= 1e7 else 1)} mi"


def _pct_rank(values: pd.Series, mask: pd.Series) -> pd.Series:
    """Percentil (0 a 1, meio-rank) entre as linhas de `mask`; NaN fora dela. Uma moeda sozinha fica em 0,5."""
    v = values.where(mask)
    n = int(v.notna().sum())
    if n == 0:
        return pd.Series(np.nan, index=values.index)
    return (v.rank(method="average") - 0.5) / n


def score_components(day: pd.DataFrame, rules: SelectionRules) -> pd.DataFrame:
    """Componentes (0 a 100) e score de cada moeda pontuável do dia. `day`: features de um dia (índice = symbol)."""
    inputs = ["momentum", "stability_50d_pct", "vol_90d_pct", "max_drawdown_180d_pct", "avg_volume_30d_usd"]
    scorable = (
        day["has_candle"].astype(bool)
        & day["history_days"].fillna(0).ge(rules.min_history_days)
        & day[inputs].notna().all(axis=1)
    )
    comps = pd.DataFrame(
        {
            "score_momentum": _pct_rank(day["momentum"], scorable),
            "score_stability": _pct_rank(day["stability_50d_pct"], scorable),
            "score_risk": (_pct_rank(-day["vol_90d_pct"], scorable) + _pct_rank(day["max_drawdown_180d_pct"], scorable)) / 2.0,
            "score_liquidity": _pct_rank(day["avg_volume_30d_usd"], scorable),
        },
        index=day.index,
    )
    w = rules.weights
    score = (
        w["momentum"] * comps["score_momentum"] + w["stability"] * comps["score_stability"]
        + w["risk"] * comps["score_risk"] + w["liquidity"] * comps["score_liquidity"]
    )
    return (comps * 100.0).assign(score=score * 100.0)


def as_float(value: object) -> float:
    """Valor numérico de uma célula (NaN se nulo)."""
    if value is None or value is pd.NA:
        return float("nan")
    return float(value) if isinstance(value, int | float | np.integer | np.floating) else float("nan")


def assess(
    day: pd.DataFrame,
    regime: str,
    rules: SelectionRules = SelectionRules(),
    unavailable: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Score, classificação, motivos e seleção de cada moeda num dia (SELECTION_SCHEMA, uma linha por moeda).

    `day`: linhas de `compute_features` de um único dia, índice = symbol. `regime`: de `regime_series` no mesmo
    dia. `unavailable`: moedas sem dado confiável hoje (symbol -> motivo, de `data_quality.availability`).
    """
    blocked_data = dict(unavailable or {})
    day = day.copy()
    comps = score_components(day, rules)
    day = day.join(comps)
    enabled = list(rules.setups)

    rows: list[dict[str, object]] = []
    for symbol, r in day.iterrows():
        sym = str(symbol)
        blockers: list[str] = []
        waits: list[str] = []
        risks: list[str] = []
        reasons: list[str] = []
        hist = int(as_float(r["history_days"])) if np.isfinite(as_float(r["history_days"])) else 0
        vol = as_float(r["vol_90d_pct"])
        maxdd = as_float(r["max_drawdown_180d_pct"])
        volume = as_float(r["avg_volume_30d_usd"])
        close, sma200, sma50 = as_float(r["close"]), as_float(r["sma_200"]), as_float(r["sma_50"])
        score = as_float(r["score"])
        met = [s for s in enabled if bool(r[f"setup_{s}"])]

        # Filtros obrigatórios (EVITAR)
        if sym in blocked_data:
            blockers.append(f"dados indisponíveis: {blocked_data[sym]}")
        elif not bool(r["has_candle"]):
            blockers.append("sem candle no dia analisado")
        if hist < rules.min_history_days:
            blockers.append(f"histórico curto: {hist} dias (mínimo {rules.min_history_days})")
        gaps = as_float(r["gap_days_365"])
        if np.isfinite(gaps) and gaps > rules.max_gap_days:
            blockers.append(f"histórico incompleto: {int(gaps)} dias sem candle no último ano")
        if not blockers and not np.isfinite(score):
            blockers.append("indicadores incompletos para calcular o score")
        if regime == REGIME_UNAVAILABLE:
            blockers.append(f"filtro de mercado ({rules.regime_symbol.split('/')[0]}) sem dados confiáveis")
        if np.isfinite(volume) and volume < rules.min_volume_usd:
            blockers.append(f"liquidez baixa: volume médio de {_musd(volume)} por dia (mínimo {_musd(rules.min_volume_usd)})")
        if np.isfinite(vol) and vol > rules.max_volatility * 100:
            blockers.append(f"volatilidade excessiva: {_num(vol, 0)}% ao ano (máximo {_num(rules.max_volatility * 100, 0)}%)")
        if np.isfinite(maxdd) and maxdd < -rules.max_drawdown * 100:
            blockers.append(f"queda excessiva: {_pct(maxdd, 0)} em 180 dias (máximo −{_num(rules.max_drawdown * 100, 0)}%)")
        if np.isfinite(close) and np.isfinite(sma200) and close < sma200:
            blockers.append(f"tendência de baixa: preço {_num(abs(close / sma200 - 1) * 100)}% abaixo da média de 200 dias")
        if sym in rules.blocklist:
            blockers.append(f"excluída manualmente da compra: {rules.blocklist[sym]}")

        # Condições para entrar agora (AGUARDAR)
        defensive = regime == REGIME_DEFENSIVE
        if defensive and rules.regime_filter == FILTER_BLOCK:
            waits.append("mercado defensivo: o Bitcoin está abaixo da média de 200 dias e a regra de risco bloqueia compras novas")
        r90, r30 = as_float(r["ret_90d_pct"]), as_float(r["ret_30d_pct"])
        if np.isfinite(r90) and r90 <= 0:
            waits.append(f"momento fraco: {_pct(r90)} em 90 dias")
        if len(met) < rules.min_conditions:
            waits.append(f"evidência insuficiente: {len(met)} de {len(enabled)} condições favoráveis (mínimo {rules.min_conditions})")
        stretch = as_float(r["stretch_50"])
        if np.isfinite(stretch) and stretch > rules.max_stretch:
            waits.append(f"subiu rápido demais: {_num((close / sma50 - 1) * 100)}% acima da média de 50 dias; risco de correção")
        rsi14 = as_float(r["rsi_14_sel"])
        if np.isfinite(rsi14) and rsi14 > rules.max_rsi:
            waits.append(f"sobrecomprada: RSI {_num(rsi14, 0)} (acima de {_num(rules.max_rsi, 0)})")
        if np.isfinite(score) and score < rules.score_moderate:
            waits.append(f"score {_num(score, 0)} abaixo do mínimo de {_num(rules.score_moderate, 0)} para entrar")

        # Alertas de risco (impedem a classificação 'boa')
        if np.isfinite(vol) and vol > rules.high_volatility * 100:
            risks.append(f"volatilidade elevada: o preço oscila cerca de {_num(vol, 0)}% ao ano")
        if np.isfinite(stretch) and stretch > rules.max_stretch * 2 / 3 and stretch <= rules.max_stretch:
            risks.append(f"preço {_num((close / sma50 - 1) * 100)}% acima da média de 50 dias: risco de correção")
        dd_now = as_float(r["drawdown_now_pct"])
        if np.isfinite(dd_now) and dd_now < -15:
            risks.append(f"ainda {_num(abs(dd_now), 0)}% abaixo do topo de 180 dias")
        if np.isfinite(maxdd) and maxdd < -rules.max_drawdown * 100 * 0.6:
            risks.append(f"queda forte recente: pior queda de {_pct(maxdd, 0)} em 180 dias")
        if len(met) == rules.min_conditions and rules.min_conditions < len(enabled):
            risks.append(f"evidência limitada: {len(met)} de {len(enabled)} condições favoráveis")
        if np.isfinite(volume) and rules.min_volume_usd <= volume < 2 * rules.min_volume_usd:
            risks.append("liquidez apenas suficiente")
        if defensive and rules.regime_filter != FILTER_BLOCK:
            risks.append("mercado defensivo: Bitcoin abaixo da média de 200 dias")

        # Evidência a favor (só fatos medidos)
        if np.isfinite(close) and np.isfinite(sma200) and close > sma200:
            reasons.append(f"tendência de alta: preço {_num((close / sma200 - 1) * 100)}% acima da média de 200 dias")
        if np.isfinite(r30) and np.isfinite(r90) and r30 > 0 and r90 > 0:
            reasons.append(f"momento positivo: {_pct(r30)} em 30 dias e {_pct(r90)} em 90 dias")
        rel = as_float(r["rel_btc_90d_pct"])
        if np.isfinite(rel) and rel > 0 and sym != rules.regime_symbol:
            reasons.append(f"mais forte que o Bitcoin em 90 dias ({_num(rel)} pontos percentuais a mais)")
        stab = as_float(r["stability_50d_pct"])
        if np.isfinite(stab) and stab >= 80:
            reasons.append(f"tendência persistente: acima da média de 200 dias em {_num(stab, 0)}% dos últimos 50 dias")
        if np.isfinite(volume) and volume >= 2 * rules.min_volume_usd:
            reasons.append(f"liquidez adequada: {_musd(volume)} negociados por dia")
        if met:
            reasons.append(f"{len(met)} de {len(enabled)} condições favoráveis: " + ", ".join(SETUP_TEXT[s] for s in met))

        if blockers:
            opportunity = OPP_AVOID
        elif waits:
            opportunity = OPP_WAIT
        elif score >= rules.score_strong and not risks:
            opportunity = OPP_STRONG
        else:
            opportunity = OPP_MODERATE
        rows.append(
            {
                "symbol": sym,
                **{c: r[c] for c in SELECTION_SCHEMA if c in r.index and c != "symbol"},
                "conditions_met": len(met),
                "conditions_total": len(enabled),
                "conditions": [SETUP_TEXT[s] for s in met],
                "est_cost_pct": as_float(r["cost_per_side"]) * 2 * 100.0,
                "opportunity": opportunity,
                "reasons": reasons,
                "risks": risks,
                "blockers": blockers + waits,
            }
        )
    out = pd.DataFrame(rows, columns=[c for c in SELECTION_SCHEMA if c not in ("candidate_rank", "selected")])
    return _select(out, rules)


def _select(out: pd.DataFrame, rules: SelectionRules) -> pd.DataFrame:
    """Ordena as candidatas (boa antes de moderada, depois score) e marca as `max_candidates` melhores."""
    order = {OPP_STRONG: 0, OPP_MODERATE: 1, OPP_WAIT: 2, OPP_AVOID: 3}
    out = out.assign(_o=out["opportunity"].map(order), _s=out["score"].fillna(-1.0))
    out = out.sort_values(["_o", "_s", "symbol"], ascending=[True, False, True], ignore_index=True).drop(columns=["_o", "_s"])
    candidate = out["opportunity"].isin([OPP_STRONG, OPP_MODERATE])
    rank = candidate.cumsum().where(candidate)
    out["candidate_rank"] = rank
    out["selected"] = candidate & rank.le(rules.max_candidates)
    extra = (candidate & ~out["selected"]).tolist()
    note = f"fora das {rules.max_candidates} melhores desta análise"
    out["blockers"] = [[*b, note] if e else b for b, e in zip(out["blockers"].tolist(), extra, strict=True)]
    return out[list(SELECTION_SCHEMA)].astype(SELECTION_SCHEMA)


def features_on(features: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """As linhas de `compute_features` de um dia, com índice = symbol (vazio se o dia não existe)."""
    if day not in features.index.get_level_values("timestamp"):
        return features.iloc[0:0].droplevel("timestamp")
    return pd.DataFrame(features.xs(day, level="timestamp"))
