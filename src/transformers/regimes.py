"""Classificação causal de regimes de mercado (Fase 4): descreve o mercado em cada dia usando só o que já era
conhecido no fechamento daquele dia.

Puro (CLAUDE.md §1): recebe preços de fechamento e a data de referência ("hoje", injetada pelo entrypoint) e devolve
um DataFrame. Sem rede, disco, relógio, ambiente ou estado global. NÃO executa ordens, NÃO altera regras de compra,
venda, stop, orçamento ou risco: é uma descrição do mercado para análise. A seleção de estratégias por regime
pertence à Fase 5.

Contrato temporal
    O candle diário é rotulado pela hora de ABERTURA (dia D, 00:00 UTC) e só fecha em D+1 00:00 UTC. A linha de D usa
    apenas candles fechados até D; `known_at` = D + 1 dia é o primeiro instante em que ela pode ser usada. Candles
    com `timestamp + 1 dia > as_of` (ainda abertos) e candles posteriores a `as_of` são ignorados. Mesmo contrato de
    `selection.compute_features` e do backtest (`selection_backtest.run_weighted`): a decisão tomada no fechamento
    de D usa a linha de D e vale a partir do retorno de D+1.

Duas dimensões, independentes (nada além do necessário):
    tendência    posição do preço em relação à média móvel de 200 dias (`dist`) e inclinação dessa média em 30 dias
                 (`slope`), cada uma com zona morta. ALTA (preço acima e média não caindo), BAIXA (preço abaixo e
                 média não subindo), LATERAL (preço colado numa média plana), MISTO (sinais conflitantes ou transição).
                 O estado só muda depois de `confirm_days` dias seguidos com o mesmo sinal bruto; até lá vale o anterior.
                 Sem estado confirmado (início, ou depois de dado indisponível): INDETERMINADO.
    volatilidade desvio dos retornos log de 30 dias (anualizado) comparado ao PASSADO do próprio ativo: ALTA acima do
                 percentil 80, com histerese (só sai abaixo do 70); NORMAL no resto.

Dados ausentes nunca viram zero nem preço repetido: dia sem candle -> SEM_CANDLE; preço inválido (NaN, infinito,
<= 0) -> DADO_INVALIDO; pouco histórico -> HISTORICO_INSUFICIENTE; muitos buracos na janela -> DADOS_INCOMPLETOS. Nesses
casos o regime é INDISPONIVEL e as features ficam nulas. Não há probabilidade nem "confiança": as regras não são
um modelo calibrado, e inventar uma porcentagem seria enganoso.

Não usados, de propósito: breadth (o universo é o de hoje, com viés de sobrevivência), volume (sem definição
histórica estável), Fear & Greed (fonte externa, pode faltar; o regime não depende dela).
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Sequence
from bisect import bisect_left, bisect_right, insort
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .. import config

CLASSIFIER_VERSION = "regimes-1.0.0"
"""Muda quando a regra ou o significado de um estado muda (nunca em silêncio). Os parâmetros entram em `params_hash`."""

TREND_UP = "ALTA"
TREND_DOWN = "BAIXA"
TREND_SIDEWAYS = "LATERAL"
TREND_MIXED = "MISTO"
TREND_UNDETERMINED = "INDETERMINADO"  # dados válidos, mas nenhum estado confirmado ainda
UNAVAILABLE = "INDISPONIVEL"          # sem dado confiável para classificar (ver `status`)
TREND_STATES: tuple[str, ...] = (TREND_UP, TREND_DOWN, TREND_SIDEWAYS, TREND_MIXED)
TREND_REGIMES: tuple[str, ...] = (*TREND_STATES, TREND_UNDETERMINED, UNAVAILABLE)

VOL_HIGH = "ALTA"
VOL_NORMAL = "NORMAL"
VOL_REGIMES: tuple[str, ...] = (VOL_NORMAL, VOL_HIGH, UNAVAILABLE)

STATUS_OK = "OK"
STATUS_NO_CANDLE = "SEM_CANDLE"
STATUS_INVALID = "DADO_INVALIDO"
STATUS_SHORT_HISTORY = "HISTORICO_INSUFICIENTE"
STATUS_INCOMPLETE = "DADOS_INCOMPLETOS"
STATUSES: tuple[str, ...] = (STATUS_OK, STATUS_NO_CANDLE, STATUS_INVALID, STATUS_SHORT_HISTORY, STATUS_INCOMPLETE)

DAYS_PER_YEAR = 365
ONE_DAY = pd.Timedelta(days=1)

REGIME_SCHEMA: dict[str, str] = {
    "timestamp": "datetime64[ns, UTC]",    # dia D (abertura do candle)
    "known_at": "datetime64[ns, UTC]",     # D + 1 dia: fechamento do candle, primeiro instante de uso permitido
    "symbol": "string",                    # ativo de referência (config.REGIME_SYMBOL)
    "close": "float64",                    # fechamento observado de D (nulo se SEM_CANDLE ou DADO_INVALIDO)
    "dist_ma_pct": "float64",              # (fechamento / média móvel - 1) em %; nulo se status != OK
    "slope_ma_pct": "float64",             # variação da média móvel em `slope_days` dias, em %; nulo se status != OK
    "vol_ann_pct": "float64",              # volatilidade realizada anualizada, em %; nulo se vol_status != OK
    "vol_rank_pct": "float64",             # posição da volatilidade de hoje entre as do passado (0 a 100); nulo antes do aquecimento
    "trend_raw": "string",                 # sinal bruto do dia, antes da confirmação (nulo se status != OK)
    "trend_regime": "string",              # TREND_REGIMES
    "vol_regime": "string",                # VOL_REGIMES
    "status": "string",                    # STATUSES, para a dimensão de tendência
    "vol_status": "string",                # STATUSES, para a dimensão de volatilidade
    "legacy_regime": "string",             # regime antigo de selection.regime_series (FAVORAVEL/NEUTRO/DEFENSIVO/INDISPONIVEL), só para comparação
    "classifier_version": "string",
    "params_hash": "string",               # fingerprint dos parâmetros (RegimeRules)
    "data_fingerprint": "string",          # encadeado: depende só dos preços até D (mesmo prefixo -> mesmo valor)
}


@dataclass(frozen=True)
class RegimeRules:
    ma_window: int = config.REGIME_MA_WINDOW
    slope_days: int = config.REGIME_SLOPE_DAYS
    trend_band: float = config.REGIME_TREND_BAND
    slope_flat: float = config.REGIME_SLOPE_FLAT
    confirm_days: int = config.REGIME_CONFIRM_DAYS
    vol_window: int = config.REGIME_VOL_WINDOW
    vol_enter: float = config.REGIME_VOL_ENTER
    vol_exit: float = config.REGIME_VOL_EXIT
    vol_min_history: int = config.REGIME_VOL_MIN_HISTORY
    min_coverage: float = config.REGIME_MIN_COVERAGE

    def __post_init__(self) -> None:
        if self.ma_window < 2 or self.slope_days < 1 or self.vol_window < 2 or self.confirm_days < 1:
            raise ValueError("janelas e confirm_days precisam ser positivos (ma_window e vol_window >= 2)")
        if self.trend_band < 0 or self.slope_flat < 0:
            raise ValueError("trend_band e slope_flat precisam ser >= 0")
        if not 0.0 <= self.vol_exit <= self.vol_enter <= 1.0:
            raise ValueError("precisa 0 <= vol_exit <= vol_enter <= 1")
        if not 0.0 < self.min_coverage <= 1.0:
            raise ValueError("min_coverage precisa estar em (0, 1]")
        if self.vol_min_history < 1:
            raise ValueError("vol_min_history precisa ser >= 1")

    def fingerprint(self) -> str:
        """Hash curto e estável dos parâmetros e da versão do classificador."""
        payload = json.dumps({"version": CLASSIFIER_VERSION, **asdict(self)}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def trend_warmup_days(self) -> int:
        """Dias de histórico (a contar do primeiro candle válido) até a primeira classificação de tendência."""
        return self.ma_window - 1 + self.slope_days


def empty_regimes() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in REGIME_SCHEMA.items()})


def last_closed_day(as_of: pd.Timestamp) -> pd.Timestamp:
    """Último dia D cujo candle diário já fechou em `as_of` (D + 1 dia <= as_of)."""
    return pd.Timestamp((as_of.tz_convert("UTC") - ONE_DAY).floor("D"))


def _check_index(index: pd.Index) -> pd.DatetimeIndex:
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise ValueError("o índice dos preços precisa ser DatetimeIndex com fuso (UTC)")
    utc = index.tz_convert("UTC")
    if not bool((utc == utc.floor("D")).all()):
        raise ValueError("candles diários precisam estar rotulados em 00:00 UTC")
    return utc


def _chain(raw: np.ndarray, calendar: pd.DatetimeIndex, rules_hash: str) -> list[str]:
    """Fingerprint encadeado: h[D] = sha256(h[D-1] | dia | fechamento bruto). Depende só dos dados até D."""
    out: list[str] = []
    state = rules_hash.encode()
    stamps = calendar.tz_convert(None).to_numpy(dtype="datetime64[ns]").astype("int64")
    for stamp, value in zip(stamps, raw, strict=True):
        state = hashlib.sha256(state + struct.pack("<qd", int(stamp), float(value))).digest()
        out.append(state.hex()[:16])
    return out


def _trend_raw(dist: float, slope: float, rules: RegimeRules) -> str:
    price = 1 if dist > rules.trend_band else -1 if dist < -rules.trend_band else 0
    ma = 1 if slope > rules.slope_flat else -1 if slope < -rules.slope_flat else 0
    if price == 1 and ma >= 0:
        return TREND_UP
    if price == -1 and ma <= 0:
        return TREND_DOWN
    if price == 0 and ma == 0:
        return TREND_SIDEWAYS
    return TREND_MIXED


def confirm_trend(raw: Sequence[str | None], confirm_days: int) -> list[str]:
    """Sinal bruto -> regime de tendência, com confirmação por persistência. Causal: o dia i só olha para trás.

    Um estado novo só vale depois de `confirm_days` dias seguidos com o mesmo sinal bruto; até lá vale o estado
    anterior. `None` (dia sem dado confiável) vira INDISPONIVEL e apaga o estado: depois de um buraco, o regime
    recomeça INDETERMINADO em vez de arrastar um estado velho.
    """
    out: list[str] = []
    confirmed = TREND_UNDETERMINED
    pending: str | None = None
    streak = 0
    for label in raw:
        if label is None:
            out.append(UNAVAILABLE)
            confirmed, pending, streak = TREND_UNDETERMINED, None, 0
            continue
        if label == confirmed:
            pending, streak = None, 0
        else:
            streak = streak + 1 if label == pending else 1
            pending = label
            if streak >= confirm_days:
                confirmed, pending, streak = label, None, 0
        out.append(confirmed)
    return out


def classify_market_regimes(
    close: pd.Series,
    as_of: pd.Timestamp,
    rules: RegimeRules = RegimeRules(),
    *,
    symbol: str = config.REGIME_SYMBOL,
    legacy: pd.Series | None = None,
) -> pd.DataFrame:
    """Regime de mercado de cada dia, do primeiro candle até o último dia fechado em `as_of` (REGIME_SCHEMA).

    `close`: fechamentos diários do ativo de referência (índice = abertura do candle, UTC, 00:00). Duplicados: vale o
    último. `as_of`: data e hora da análise, injetada. `legacy`: opcional, regime antigo por dia (só é anexado).
    O calendário é contínuo: dia sem candle aparece como SEM_CANDLE (nunca é pulado nem preenchido).
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of precisa ter fuso (UTC)")
    if close.empty:
        return empty_regimes()
    index = _check_index(close.index)
    series = pd.Series(close.to_numpy(dtype="float64"), index=index)
    series = series[~series.index.duplicated(keep="last")].sort_index()  # duplicado: vale o último da entrada (como clean_candles)
    last = last_closed_day(as_of)
    series = series[series.index <= last]  # candle aberto ou futuro nunca entra
    if series.empty:
        return empty_regimes()

    calendar = pd.date_range(series.index.min(), last, freq="D", tz="UTC")
    n = len(calendar)
    present = calendar.isin(series.index)
    raw = series.reindex(calendar).to_numpy(dtype="float64")
    valid = np.isfinite(raw) & (raw > 0)
    px = pd.Series(np.where(valid, raw, np.nan), index=calendar)

    ma_min = math.ceil(rules.ma_window * rules.min_coverage)
    vol_min = math.ceil(rules.vol_window * rules.min_coverage)
    ma = px.rolling(rules.ma_window, min_periods=ma_min).mean()
    dist = px / ma - 1.0
    slope = ma / ma.shift(rules.slope_days) - 1.0
    logret = pd.Series(np.log(px.to_numpy(dtype="float64")), index=calendar).diff()  # NaN se faltar um dos dois dias
    vol = logret.rolling(rules.vol_window, min_periods=vol_min).std(ddof=1) * math.sqrt(DAYS_PER_YEAR)

    first_valid = int(np.argmax(valid)) if valid.any() else n
    age = np.arange(n) - first_valid  # dias desde o primeiro candle válido

    def status_for(warmup: int, needed: np.ndarray) -> list[str]:
        out: list[str] = []
        for i in range(n):
            if not present[i]:
                out.append(STATUS_NO_CANDLE)
            elif not valid[i]:
                out.append(STATUS_INVALID)
            elif age[i] < warmup:
                out.append(STATUS_SHORT_HISTORY)
            elif not needed[i]:
                out.append(STATUS_INCOMPLETE)
            else:
                out.append(STATUS_OK)
        return out

    dist_a = dist.to_numpy(dtype="float64")
    slope_a = slope.to_numpy(dtype="float64")
    vol_a = vol.to_numpy(dtype="float64")
    status = status_for(rules.trend_warmup_days, np.isfinite(dist_a) & np.isfinite(slope_a))
    vol_status = status_for(rules.vol_window, np.isfinite(vol_a))

    # Tendência: sinal bruto + confirmação por persistência (causal: só olha para trás).
    trend_raw: list[str | None] = [
        _trend_raw(float(dist_a[i]), float(slope_a[i]), rules) if status[i] == STATUS_OK else None for i in range(n)
    ]
    trend = confirm_trend(trend_raw, rules.confirm_days)

    # Volatilidade: percentil contra o passado ESTRITO (o valor de hoje só entra na história depois de classificado).
    history: list[float] = []
    rank = np.full(n, np.nan)
    vol_regime: list[str] = []
    high = False
    for i in range(n):
        if vol_status[i] != STATUS_OK:
            vol_regime.append(UNAVAILABLE)
            high = False
            continue
        today = float(vol_a[i])
        if len(history) < rules.vol_min_history:
            vol_status[i] = STATUS_SHORT_HISTORY
            vol_regime.append(UNAVAILABLE)
        else:
            below, equal = bisect_left(history, today), bisect_right(history, today) - bisect_left(history, today)
            rank[i] = (below + 0.5 * equal) / len(history)
            if rank[i] >= rules.vol_enter:
                high = True
            elif rank[i] < rules.vol_exit:
                high = False
            vol_regime.append(VOL_HIGH if high else VOL_NORMAL)
        insort(history, today)

    ok = np.array([s == STATUS_OK for s in status])
    vol_shown = np.isfinite(vol_a) & valid & (age >= rules.vol_window)  # valor medido, mesmo antes do percentil aquecer
    legacy_col = (
        legacy.reindex(calendar).astype("string") if legacy is not None else pd.Series(pd.NA, index=calendar, dtype="string")
    )
    out = pd.DataFrame(
        {
            "timestamp": calendar,
            "known_at": calendar + ONE_DAY,
            "symbol": symbol,
            "close": np.where(valid, raw, np.nan),
            "dist_ma_pct": np.where(ok, dist_a * 100.0, np.nan),
            "slope_ma_pct": np.where(ok, slope_a * 100.0, np.nan),
            "vol_ann_pct": np.where(vol_shown, vol_a * 100.0, np.nan),
            "vol_rank_pct": rank * 100.0,
            "trend_raw": pd.Series(trend_raw, dtype="string").to_numpy(),
            "trend_regime": trend,
            "vol_regime": vol_regime,
            "status": status,
            "vol_status": vol_status,
            "legacy_regime": legacy_col.to_numpy(),
            "classifier_version": CLASSIFIER_VERSION,
            "params_hash": rules.fingerprint(),
            "data_fingerprint": _chain(raw, calendar, rules.fingerprint()),
        }
    )
    return out.astype(REGIME_SCHEMA).reset_index(drop=True)


def latest_regime(table: pd.DataFrame) -> pd.Series | None:
    """A linha do último dia classificado (None se a tabela está vazia). Pode ser INDISPONIVEL: o chamador deve checar."""
    return None if table.empty else table.iloc[-1]
