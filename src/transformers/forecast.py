"""Previsão estatística de retorno de BTC e ETH em 1, 7 e 30 dias, avaliada contra um baseline.

Puro (CLAUDE.md §1): recebe preços, períodos e a semente aleatória; não acessa rede, disco nem relógio
(a data de referência é o último dia dos preços). Só numpy e pandas.

Métodos (retorno logarítmico em `h` dias; quantis P10/P50/P90):
    PASSEIO_ALEATORIO  baseline: sem tendência, volatilidade diária da janela × √h, normal. É o "preço de hoje
                       com ruído": a mediana é o retorno zero.
    BOOTSTRAP_BLOCOS   reamostra blocos de retornos diários da janela (preserva um pouco da dependência entre
                       dias vizinhas); a mediana carrega a tendência da janela.
    EWMA               volatilidade que reage rápido (RiskMetrics, fator lambda) × √h, normal, com a tendência
                       média da janela.

Protocolo (nada do futuro entra na previsão e o teste não escolhe nada):
    1. Em cada origem (um dia), a previsão usa só os retornos até esse dia; o realizado é a soma dos `h` retornos
       seguintes. Origens a cada `h` dias, para as janelas não se sobreporem.
    2. VALIDAÇÃO: cada método tem janela, bloco e lambda escolhidos pela menor perda de quantis (pinball);
       o modelo publicado é o melhor entre BOOTSTRAP_BLOCOS e EWMA (o EWMA só aparece se os dados o justificarem).
       O baseline também escolhe a sua janela na validação.
    3. TESTE: lido uma única vez, com os parâmetros já escolhidos. Gera MAE, RMSE, erro direcional, cobertura e
       largura da faixa P10–P90 (nominal 80%), sempre ao lado das do baseline.

`beats_baseline` só é verdadeiro se o modelo vencer o baseline em perda de quantis, MAE e RMSE no teste.
`coverage_ok` exige que a cobertura medida seja compatível com 80% (intervalo binomial de 95% para o número de
janelas do teste). Sem as duas coisas, `verdict` diz "sem vantagem demonstrada sobre o preço de hoje".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

Floats = NDArray[np.float64]

HORIZONS: tuple[int, ...] = (1, 7, 30)
QUANTILES: tuple[float, float, float] = (0.1, 0.5, 0.9)
NOMINAL_COVERAGE = 0.8
Z90 = 1.2815515655446004  # quantil 90% da normal padrão

METHOD_BASELINE = "PASSEIO_ALEATORIO"
METHOD_BOOTSTRAP = "BOOTSTRAP_BLOCOS"
METHOD_EWMA = "EWMA"
ROLE_BASELINE = "BASELINE"
ROLE_MODEL = "MODELO"

FORECAST_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "horizon_days": "int64",
    "role": "string",                # BASELINE ou MODELO
    "method": "string",
    "params": "string",              # janela, bloco ou lambda escolhidos na validação
    "window_days": "int64",
    "n_obs": "int64",                # retornos diários usados na previsão de hoje
    "asof": "datetime64[ns, UTC]",   # último dia dos preços
    "last_close": "float64",
    "expected_return_pct": "float64",  # mediana (P50) do retorno em `horizon_days`, em %
    "vol_pct": "float64",            # desvio padrão do retorno no horizonte, em %
    "daily_vol_pct": "float64",
    "p10_pct": "float64",
    "p50_pct": "float64",
    "p90_pct": "float64",
    "p10_price": "float64",
    "p50_price": "float64",
    "p90_price": "float64",
    "n_eval": "int64",               # janelas do teste usadas na avaliação
    "test_start": "datetime64[ns, UTC]",
    "test_end": "datetime64[ns, UTC]",
    "mae_pct": "float64",
    "rmse_pct": "float64",
    "directional_acc": "float64",    # fração de acertos do sinal (alta/baixa); o baseline conta como "alta"
    "coverage": "float64",           # fração dos realizados dentro de P10–P90
    "coverage_nominal": "float64",
    "coverage_ok": "bool",
    "width_pct": "float64",          # largura média da faixa P10–P90, em pontos percentuais
    "pinball_pct": "float64",        # perda de quantis média (menor é melhor)
    "base_mae_pct": "float64",
    "base_rmse_pct": "float64",
    "base_directional_acc": "float64",
    "base_coverage": "float64",
    "base_width_pct": "float64",
    "base_pinball_pct": "float64",
    "beats_baseline": "bool",
    "verdict": "string",
}


@dataclass(frozen=True)
class ForecastRules:
    windows: tuple[int, ...] = (180, 365, 730)
    blocks: tuple[int, ...] = (5, 10, 20)
    ewma_lambdas: tuple[float, ...] = (0.94, 0.97, 0.99)
    sims: int = 1000


# (q10, q50, q90, desvio padrão do retorno no horizonte)
Prediction = tuple[float, float, float, float]
Predictor = Callable[[int, np.random.Generator], Prediction]  # (índice da origem, gerador) -> previsão


@dataclass(frozen=True)
class Metrics:
    n: int
    mae: float
    rmse: float
    directional: float
    coverage: float
    width: float
    pinball: float


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in FORECAST_SCHEMA.items()})


def _pinball(y: Floats, q10: Floats, q50: Floats, q90: Floats) -> float:
    loss = 0.0
    for q, f in zip(QUANTILES, (q10, q50, q90), strict=True):
        diff = y - f
        loss += float(np.mean(np.maximum(q * diff, (q - 1.0) * diff)))
    return loss / len(QUANTILES)


def _score(y: Floats, q10: Floats, q50: Floats, q90: Floats) -> Metrics:
    err = y - q50
    return Metrics(
        n=len(y),
        mae=float(np.mean(np.abs(err))),
        rmse=float(np.sqrt(np.mean(err**2))),
        directional=float(np.mean((q50 >= 0.0) == (y > 0.0))),  # mediana zero conta como "alta"
        coverage=float(np.mean((y >= q10) & (y <= q90))),
        width=float(np.mean(q90 - q10)),
        pinball=_pinball(y, q10, q50, q90),
    )


# ---------------------------------------------------------------------------------------------
# Métodos
# ---------------------------------------------------------------------------------------------

def _random_walk(lr: Floats, h: int, window: int) -> Predictor:
    def predict(i: int, rng: np.random.Generator) -> Prediction:
        sigma = float(np.std(lr[max(i + 1 - window, 0): i + 1], ddof=1)) * np.sqrt(h)
        return -Z90 * sigma, 0.0, Z90 * sigma, sigma

    return predict


def _bootstrap(lr: Floats, h: int, window: int, block: int, sims: int) -> Predictor:
    length = min(block, h)
    n_blocks = -(-h // length)

    def predict(i: int, rng: np.random.Generator) -> Prediction:
        sample = lr[max(i + 1 - window, 0): i + 1]
        starts = rng.integers(0, len(sample) - length + 1, size=(sims, n_blocks))
        idx = (starts[:, :, None] + np.arange(length)).reshape(sims, n_blocks * length)[:, :h]
        sums = sample[idx].sum(axis=1)
        q10, q50, q90 = np.quantile(sums, QUANTILES)
        return float(q10), float(q50), float(q90), float(sums.std())

    return predict


def _ewma(lr: Floats, h: int, window: int, lam: float) -> Predictor:
    # Variância EWMA causal: o valor no dia i só usa retornos até i (calculada uma vez para a série toda).
    variance = pd.Series(lr**2).ewm(alpha=1.0 - lam, adjust=False).mean().to_numpy(dtype="float64")

    def predict(i: int, rng: np.random.Generator) -> Prediction:
        sigma = float(np.sqrt(variance[i])) * np.sqrt(h)
        mu = float(np.mean(lr[max(i + 1 - window, 0): i + 1])) * h
        return mu - Z90 * sigma, mu, mu + Z90 * sigma, sigma

    return predict


# ---------------------------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------------------------

def _origins(days: pd.DatetimeIndex, n: int, h: int, period: tuple[pd.Timestamp, pd.Timestamp]) -> Sequence[int]:
    """Índices dos dias de origem no período, de `h` em `h` dias.

    O realizado (os `h` dias seguintes) tem de existir e terminar dentro do período: assim a validação nunca
    olha para dentro do teste, nem por alguns dias.
    """
    idx = np.arange(n)
    realized_end = days[np.minimum(idx + h, n - 1)]
    inside = np.flatnonzero((days >= period[0]) & (idx + h < n) & (realized_end <= period[1]))
    return [int(i) for i in inside[::h]]


def _walk_forward(
    lr: Floats, h: int, origins: Sequence[int], predictor: Predictor, entropy: Sequence[int]
) -> tuple[Metrics, Floats, Floats]:
    """Previsões nas origens (só com dados até a origem) contra o realizado. Devolve métricas e (y, q50)."""
    rng = np.random.default_rng(list(entropy))  # mesma sequência sorteada para todo candidato (comparação justa)
    y = np.empty(len(origins))
    quantiles = np.empty((len(origins), 3))
    for k, i in enumerate(origins):
        q10, q50, q90, _ = predictor(i, rng)
        quantiles[k] = (q10, q50, q90)
        y[k] = lr[i + 1: i + 1 + h].sum()
    return _score(y, quantiles[:, 0], quantiles[:, 1], quantiles[:, 2]), y, quantiles[:, 1]


@dataclass(frozen=True)
class Candidate:
    method: str
    params: str
    window: int
    predictor: Predictor


def _candidates(lr: Floats, h: int, rules: ForecastRules) -> dict[str, list[Candidate]]:
    base = [Candidate(METHOD_BASELINE, f"janela={w}", w, _random_walk(lr, h, w)) for w in rules.windows]
    boot = [
        Candidate(METHOD_BOOTSTRAP, f"janela={w}, bloco={b}", w, _bootstrap(lr, h, w, b, rules.sims))
        for w in rules.windows
        for b in rules.blocks
    ]
    ewma = [
        Candidate(METHOD_EWMA, f"janela={w}, lambda={lam:g}", w, _ewma(lr, h, w, lam))
        for w in rules.windows
        for lam in rules.ewma_lambdas
    ]
    return {METHOD_BASELINE: base, METHOD_BOOTSTRAP: boot, METHOD_EWMA: ewma}


def _best(
    options: list[Candidate], lr: Floats, h: int, origins: Sequence[int], entropy: Sequence[int]
) -> tuple[Candidate, float]:
    """Candidato de menor perda de quantis nas origens da VALIDAÇÃO."""
    scored = [(_walk_forward(lr, h, origins, c.predictor, entropy)[0].pinball, c) for c in options]
    loss, winner = min(scored, key=lambda t: t[0])
    return winner, loss


# ---------------------------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------------------------

def _verdict(role: str, beats: bool, coverage_ok: bool, coverage: float) -> str:
    if role == ROLE_BASELINE:
        return "referência: o preço de hoje, com ruído"
    if not beats:
        return "sem vantagem demonstrada sobre o preço de hoje"
    if not coverage_ok:
        return f"melhor que o preço de hoje, mas a faixa não é confiável (cobertura {coverage * 100:.0f}% contra 80%)"
    return "vantagem demonstrada no período de teste"


def _coverage_ok(coverage: float, n: int) -> bool:
    if n == 0:
        return False
    return bool(abs(coverage - NOMINAL_COVERAGE) <= 1.96 * np.sqrt(NOMINAL_COVERAGE * (1 - NOMINAL_COVERAGE) / n))


def _row(
    symbol: str, h: int, role: str, c: Candidate, lr: Floats, asof: pd.Timestamp, last_close: float,
    test: tuple[pd.Timestamp, pd.Timestamp], m: Metrics, base: Metrics, beats: bool, entropy: Sequence[int],
) -> dict[str, object]:
    last = len(lr) - 1
    q10, q50, q90, sigma = c.predictor(last, np.random.default_rng(list(entropy)))
    daily_sigma = float(np.std(lr[max(last + 1 - c.window, 0): last + 1], ddof=1))
    ok = _coverage_ok(m.coverage, m.n)
    return {
        "symbol": symbol, "horizon_days": h, "role": role, "method": c.method, "params": c.params,
        "window_days": c.window, "n_obs": min(c.window, len(lr)), "asof": asof, "last_close": last_close,
        "expected_return_pct": (np.exp(q50) - 1.0) * 100.0, "vol_pct": sigma * 100.0, "daily_vol_pct": daily_sigma * 100.0,
        "p10_pct": (np.exp(q10) - 1.0) * 100.0, "p50_pct": (np.exp(q50) - 1.0) * 100.0, "p90_pct": (np.exp(q90) - 1.0) * 100.0,
        "p10_price": last_close * np.exp(q10), "p50_price": last_close * np.exp(q50), "p90_price": last_close * np.exp(q90),
        "n_eval": m.n, "test_start": test[0], "test_end": test[1],
        "mae_pct": m.mae * 100.0, "rmse_pct": m.rmse * 100.0, "directional_acc": m.directional,
        "coverage": m.coverage, "coverage_nominal": NOMINAL_COVERAGE, "coverage_ok": ok,
        "width_pct": m.width * 100.0, "pinball_pct": m.pinball * 100.0,
        "base_mae_pct": base.mae * 100.0, "base_rmse_pct": base.rmse * 100.0,
        "base_directional_acc": base.directional, "base_coverage": base.coverage, "base_width_pct": base.width * 100.0,
        "base_pinball_pct": base.pinball * 100.0,
        "beats_baseline": beats, "verdict": _verdict(role, beats, ok, m.coverage),
    }


def forecast_table(
    closes: pd.DataFrame,
    symbols: Sequence[str],
    validation: tuple[pd.Timestamp, pd.Timestamp],
    test: tuple[pd.Timestamp, pd.Timestamp],
    seed: int,
    horizons: Sequence[int] = HORIZONS,
    rules: ForecastRules = ForecastRules(),
) -> pd.DataFrame:
    """Previsão de hoje e avaliação walk-forward por ativo e horizonte (FORECAST_SCHEMA).

    `closes`: fechamentos diários (índice UTC, uma coluna por símbolo). `seed`: semente injetada; o resultado é
    o mesmo para a mesma semente. Ativo sem dados para a janela maior e para a validação fica de fora.
    """
    rows: list[dict[str, object]] = []
    for s_idx, symbol in enumerate(symbols):
        if symbol not in closes.columns:
            continue
        px = closes[symbol].dropna()
        px = px[px.gt(0)]
        if len(px) <= max(rules.windows) + 2:
            continue
        lr = np.diff(np.log(px.to_numpy(dtype="float64")))
        days = pd.DatetimeIndex(px.index[1:])  # o retorno do dia i é close_i / close_{i-1}
        asof = pd.Timestamp(px.index[-1])
        last_close = float(px.iloc[-1])
        for h in horizons:
            valid_origins = _origins(days, len(lr), h, validation)
            test_origins = _origins(days, len(lr), h, test)
            if not valid_origins or not test_origins:
                continue
            entropy = (seed, s_idx, h)
            options = _candidates(lr, h, rules)
            baseline, _ = _best(options[METHOD_BASELINE], lr, h, valid_origins, entropy)
            boot, boot_loss = _best(options[METHOD_BOOTSTRAP], lr, h, valid_origins, entropy)
            ewma, ewma_loss = _best(options[METHOD_EWMA], lr, h, valid_origins, entropy)
            model = boot if boot_loss <= ewma_loss else ewma

            # TESTE: lido uma única vez, só com os candidatos já escolhidos.
            base_m, _, _ = _walk_forward(lr, h, test_origins, baseline.predictor, entropy)
            model_m, _, _ = _walk_forward(lr, h, test_origins, model.predictor, entropy)
            beats = model_m.pinball < base_m.pinball and model_m.rmse < base_m.rmse and model_m.mae < base_m.mae
            span = (pd.Timestamp(days[test_origins[0]]), pd.Timestamp(days[test_origins[-1]]))
            rows.append(_row(symbol, h, ROLE_BASELINE, baseline, lr, asof, last_close, span, base_m, base_m, False, entropy))
            rows.append(_row(symbol, h, ROLE_MODEL, model, lr, asof, last_close, span, model_m, base_m, beats, entropy))
    if not rows:
        return _empty()
    return pd.DataFrame(rows)[list(FORECAST_SCHEMA)].astype(FORECAST_SCHEMA)
