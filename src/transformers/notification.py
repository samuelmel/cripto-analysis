"""Mensagem do dia para o celular: dados entram, lista de textos sai (cada um com no máximo 4096 caracteres).

Puro (CLAUDE.md §1): sem rede, disco, relógio nem variáveis de ambiente; "agora" e os segredos a esconder são
parâmetros. O envio é de `src.notifiers`.

Conteúdo: data/hora e atualidade dos dados; para BTC e ETH, preço, fechamento diário usado, SMA 200, distância,
filtro do BTC, sinal, a condição que sustenta e a que invalidaria, e a previsão de 1, 7 e 30 dias com a faixa e a
limitação; o aviso de pânico em seção separada; as outras moedas só quando algo relevante mudou, sempre dizendo
que monitorar não é autorizar compra. Não há ponto de entrada inventado: os únicos níveis citados são os da
própria regra (a SMA 200 atual). Sem aconselhamento personalizado.

Dados parciais: a mensagem abre com as limitações e marca os sinais como NÃO CONFIÁVEIS; moeda sem dado
confiável aparece como INDISPONÍVEL, com o motivo, e sem previsão.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta, timezone

import pandas as pd

TELEGRAM_LIMIT = 4096
FORTALEZA = timezone(timedelta(hours=-3))  # UTC−3 o ano todo (sem horário de verão)

STAGE_BUY = "COMPRAR"
STAGE_WATCH = "PREPARAR"
STAGE_UNAVAILABLE = "INDISPONÍVEL"
SIGNAL_SELL = "VENDER"
ALERT_SELL = "VENDER AGORA"

_SECONDARY_SOURCES = {"coingecko", "alternative_me"}
_ICON = {STAGE_BUY: "🟢", STAGE_WATCH: "🟡", "NEUTRO": "⚪", SIGNAL_SELL: "🔴", STAGE_UNAVAILABLE: "⚫"}
_OTHER_ALERTS = {
    "COMPRAR AGORA": "entrou em tendência de alta",
    "VENDER AGORA": "saiu da tendência de alta",
    "NO RADAR": "chegou perto de voltar à tendência de alta",
    "SAIU DO RADAR": "saiu do radar",
}
_BAD_TOKEN = re.compile(r"\b(nan|inf|None)\b|<NA>|NaT")
DISCLAIMER = "Estatística sobre o passado, não recomendação de investimento."


def _num(x: float, digits: int = 2) -> str:
    return f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _usd(x: float) -> str:
    return f"US$ {_num(x, 2 if abs(x) < 1000 else 0)}"


def _pct(x: float, digits: int = 1) -> str:
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{_num(abs(x), digits)}%"


def _day(ts: pd.Timestamp) -> str:
    return f"{ts:%d/%m}"


def redact(text: str, secrets: Sequence[str]) -> str:
    """Troca cada segredo (token, chave de API) que apareça em `text` por ***."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


# ---------------------------------------------------------------------------------------------
# Divisão e validação
# ---------------------------------------------------------------------------------------------

def _pack(pieces: Sequence[str], sep: str, limit: int, finer: Sequence[str]) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        for part in (_split(piece, finer, limit) if len(piece) > limit else [piece]):
            joined = part if not current else current + sep + part
            if len(joined) <= limit:
                current = joined
            else:
                chunks.append(current)
                current = part
    if current:
        chunks.append(current)
    return chunks


def _split(text: str, separators: Sequence[str], limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    if not separators:
        return [text[i: i + limit] for i in range(0, len(text), limit)]
    sep, finer = separators[0], separators[1:]
    return _pack(text.split(sep), sep, limit, finer)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Divide em pedaços de no máximo `limit` caracteres, cortando em parágrafo, depois linha, depois palavra."""
    return [c for c in _split(text, ("\n\n", "\n", " "), limit) if c.strip()]


def validate_messages(texts: Sequence[str], secrets: Sequence[str] = (), limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Problemas que impedem o envio: lista vazia, texto vazio, acima do limite, segredo ou valor inválido no texto."""
    if not texts:
        return ["nenhuma mensagem gerada"]
    problems: list[str] = []
    for i, text in enumerate(texts, start=1):
        if not text.strip():
            problems.append(f"mensagem {i} vazia")
        if len(text) > limit:
            problems.append(f"mensagem {i} com {len(text)} caracteres (limite {limit})")
        if any(s and s in text for s in secrets):
            problems.append(f"mensagem {i} contém um segredo")
        bad = _BAD_TOKEN.search(text)
        if bad:
            problems.append(f"mensagem {i} contém o valor inválido '{bad.group(0)}'")
    return problems


# ---------------------------------------------------------------------------------------------
# Relatório do dia
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Coin:
    """Uma linha de `daily_signals` com tipos explícitos (a entrada do formatador, sem Series do pandas)."""

    symbol: str
    timestamp: pd.Timestamp
    close: float
    sma_200: float | None
    stage: str
    stage_reason: str | None
    alert: str | None
    panic: bool
    regime_up: bool

    @property
    def name(self) -> str:
        return self.symbol.split("/")[0]

    @property
    def signal(self) -> str:
        if self.stage == STAGE_UNAVAILABLE:
            return STAGE_UNAVAILABLE
        return SIGNAL_SELL if self.alert == ALERT_SELL else self.stage


def _opt_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not math.isnan(value) else None


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None  # pd.NA e None viram None


def _coins(signals: pd.DataFrame) -> dict[str, Coin]:
    coins: dict[str, Coin] = {}
    for r in signals.to_dict("records"):
        symbol = str(r["symbol"])
        coins[symbol] = Coin(
            symbol=symbol,
            timestamp=pd.Timestamp(r["timestamp"]),
            close=float(r["close"]),
            sma_200=_opt_float(r["sma_200"]),
            stage=str(r["stage"]),
            stage_reason=_opt_str(r["stage_reason"]),
            alert=_opt_str(r["alert"]),
            panic=bool(r["panic"]),
            regime_up=bool(r["regime_up"]),
        )
    return coins


def _reasons(c: Coin, sma: float, regime: Coin | None) -> list[str]:
    """Condição que sustenta o sinal e a que o invalidaria (ou o mudaria), só com os níveis da regra."""
    own = regime is None or c.symbol == regime.symbol
    r_name = "BTC" if regime is None else regime.name
    r_sma = None if regime is None else regime.sma_200
    both = "" if own or r_sma is None else f" e o {r_name} fechar acima de {_usd(r_sma)}"
    if c.signal == STAGE_BUY:
        also = "" if own or r_sma is None else f" ou o {r_name} fechar abaixo de {_usd(r_sma)}"
        return [
            f"Sustenta: fechou acima da SMA 200{'' if own else f' e o {r_name} também'}.",
            f"Invalida: fechar abaixo de {_usd(sma)} (SMA 200 atual){also}.",
        ]
    if c.signal == STAGE_WATCH:
        return [
            "Sustenta: está até 3% abaixo da SMA 200 e subindo.",
            f"Vira COMPRAR: fechar acima de {_usd(sma)}{both}. Sai do radar se cair mais de 3% abaixo.",
        ]
    below = c.close < sma
    why = "fechou abaixo da SMA 200" if below else f"o {r_name} fechou abaixo da SMA 200 dele"
    if c.signal == SIGNAL_SELL:
        return [f"Sustenta: saiu da tendência de alta hoje ({why}).", f"Volta a COMPRAR: fechar acima de {_usd(sma)}{both}."]
    return [f"Sustenta: {why if below else f'o {r_name} está abaixo da SMA 200 dele'}.", f"Vira COMPRAR: fechar acima de {_usd(sma)}{both}."]


def _forecast_lines(symbol: str, forecast: pd.DataFrame) -> list[str]:
    rows = sorted(
        (r for r in forecast.to_dict("records") if r["symbol"] == symbol and r["role"] == "MODELO"),
        key=lambda r: int(r["horizon_days"]),
    )
    if not rows:
        return ["Previsão: indisponível."]
    bands = [f"{int(r['horizon_days'])}d {_pct(float(r['p10_pct']), 0)} a {_pct(float(r['p90_pct']), 0)}" for r in rows]
    lines = ["Previsão (estimativa, faixa P10–P90): " + " · ".join(bands)]
    winners = [f"{int(r['horizon_days'])}d" for r in rows if bool(r["beats_baseline"])]
    if not winners:
        lines.append("Sem vantagem demonstrada sobre o preço de hoje: use como faixa de incerteza, não como palpite.")
    else:
        lines.append(f"Vantagem demonstrada sobre o preço de hoje só em: {', '.join(winners)}.")
    off = [f"{int(r['horizon_days'])}d {_num(float(r['coverage']) * 100, 0)}%" for r in rows if not bool(r["coverage_ok"])]
    if off:
        lines.append(f"Faixa pouco calibrada no teste (cobertura medida, nominal 80%): {', '.join(off)}.")
    return lines


def format_report(
    signals: pd.DataFrame,
    forecast: pd.DataFrame,
    *,
    now: pd.Timestamp,
    recommended: Sequence[str],
    regime_symbol: str,
    max_stale_days: int,
    source_errors: pd.DataFrame | None = None,
) -> list[str]:
    """Mensagens do dia (já divididas em até 4096 caracteres)."""
    local = now.tz_convert(FORTALEZA)
    expected = now.floor("D") - pd.Timedelta(days=1)  # último candle fechado esperado
    coins = _coins(signals)
    core = [coins[s] for s in recommended if s in coins]
    regime = coins.get(regime_symbol)
    errors = source_errors if source_errors is not None else pd.DataFrame(columns=["source", "scope", "detail"])

    lag = {c.symbol: int((expected - c.timestamp).days) for c in core}
    binance_failed = [str(e.scope) for e in errors.itertuples() if str(e.source) == "binance"]
    secondary = sorted({str(e.source) for e in errors.itertuples() if str(e.source) in _SECONDARY_SOURCES})
    unavailable = [c.symbol for c in core if c.signal == STAGE_UNAVAILABLE]
    partial = bool(
        set(binance_failed) & set(recommended) or unavailable or any(v > 0 for v in lag.values()) or len(core) < len(recommended)
    )

    header = [f"📊 Monitor cripto — {local:%d/%m/%Y %H:%M} (Fortaleza) · {now:%d/%m %H:%M} UTC"]
    out: list[str] = []
    if core:
        worst = max(lag.values())
        state = "em dia" if worst <= 0 else f"ATRASADO {worst} dia(s)"
        header.append(f"Dados: candle diário fechado de {_day(max(c.timestamp for c in core))} (UTC), {state}.")
    fng = signals["fng_value"].dropna()
    if not fng.empty:
        header.append(f"Humor do mercado (Fear & Greed): {int(fng.iloc[0])} de 100.")

    out.append("\n".join(header))
    limits: list[str] = []
    if partial:
        limits.append("⚠️ DADOS PARCIAIS: os sinais abaixo NÃO são confiáveis até a coleta voltar ao normal.")
    if binance_failed:
        names = ", ".join(m.split("/")[0] for m in binance_failed)
        limits.append(f"Falha na coleta de preços ({names}); moedas sem preço novo ficam INDISPONÍVEIS.")
    if secondary:
        limits.append(
            f"Fonte secundária fora do ar ({', '.join(secondary)}): sem market cap e/ou humor do mercado; "
            "os sinais por preço seguem valendo."
        )
    if len(core) < len(recommended):
        missing = ", ".join(s.split("/")[0] for s in recommended if s not in coins)
        limits.append(f"Sem dados de {missing}.")
    if limits:
        out.append("\n".join(limits))

    for c in core:
        signal = c.signal
        head = f"{_ICON.get(signal, '⚪')} {c.name} — {signal}"
        if signal == STAGE_UNAVAILABLE or c.sma_200 is None:
            out.append(f"{head}\nMotivo: {c.stage_reason or 'dado insuficiente'}.\nSem sinal e sem previsão para esta moeda hoje.")
            continue
        if partial:
            head += " (NÃO CONFIÁVEL: dados parciais)"
        dist = (c.close / c.sma_200 - 1.0) * 100.0
        if regime is None:
            filt = "n/d"
        else:
            filt = f"{regime.name} {'acima' if regime.regime_up else 'abaixo'} da SMA 200 dele ({'ok' if regime.regime_up else 'bloqueia compra'})"
        out.append(
            "\n".join(
                [
                    head,
                    f"Preço {_usd(c.close)} (fechamento diário de {_day(c.timestamp)})",
                    f"SMA 200: {_usd(c.sma_200)} · preço {_num(abs(dist), 1)}% {'acima' if dist >= 0 else 'abaixo'} da média",
                    f"Filtro do BTC: {filt}",
                    *_reasons(c, c.sma_200, regime),
                    *_forecast_lines(c.symbol, forecast),
                ]
            )
        )

    panic = [c.name for c in coins.values() if c.panic]
    out.append(
        "⚠️ Aviso de pânico (não é recomendação de compra)\n"
        + (f"Pânico em: {', '.join(panic)}. Queda forte com medo no mercado; comprar no pânico perdeu dinheiro nos testes."
           if panic else "Nenhuma moeda em pânico.")
    )

    others = [
        f"{c.name}: {_OTHER_ALERTS[c.alert]}"
        for c in coins.values()
        if c.symbol not in recommended and c.alert in _OTHER_ALERTS and c.stage != STAGE_UNAVAILABLE
    ]
    if others:
        out.append(
            "Outras moedas (só acompanhadas)\n" + "\n".join(others)
            + "\nMonitorar não é autorizar compra: a regra só recomenda BTC e ETH."
        )
    out.append(DISCLAIMER)
    return split_message("\n\n".join(out))


def format_error(stage: str, detail: str, *, now: pd.Timestamp, secrets: Sequence[str] = ()) -> list[str]:
    """Alerta curto de falha do pipeline. O detalhe é cortado em 300 caracteres e sem segredos."""
    clean = redact(" ".join(detail.split()), secrets)
    short = clean if len(clean) <= 300 else clean[:297] + "..."
    local = now.tz_convert(FORTALEZA)
    return split_message(
        f"🔴 crypto-analyzer: o pipeline falhou ({local:%d/%m/%Y %H:%M} Fortaleza)\n"
        f"Etapa: {stage}\nErro: {short}\n"
        "Os sinais publicados antes podem estar desatualizados; não use como atuais."
    )
