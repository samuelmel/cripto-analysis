"""Mensagem do dia para o celular: dados entram, lista de textos sai (cada um com no máximo 4096 caracteres).

Puro (CLAUDE.md §1): sem rede, disco, relógio nem variáveis de ambiente; "agora" e os segredos a esconder são
parâmetros. O envio é de `src.notifiers`.

Conteúdo (curto, para ler em um minuto): data/hora e atualidade dos dados, orçamento da simulação, estado do
mercado, só as moedas selecionadas (até MAX_CANDIDATES) com aporte, classificação, motivo e principal risco, o
resumo do aporte (total, saldo não alocado, decisão), alertas essenciais (virada da regra SMA 200 de BTC/ETH,
pânico) e a evidência do backtest. Tudo vem da recomendação calculada pelo pipeline (`recommendation.py`): o
formatador não calcula aporte nem escolhe moeda. Os indicadores detalhados ficam no painel.

Sem oportunidade: a frase fixa NO_OPPORTUNITY e os motivos mais frequentes. Dados parciais: a mensagem lista as
limitações; moeda sem dado confiável nunca é recomendada (é bloqueada antes, em `selection.assess`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta, timezone

import numpy as np
import pandas as pd

TELEGRAM_LIMIT = 4096
FORTALEZA = timezone(timedelta(hours=-3))  # UTC−3 o ano todo (sem horário de verão)

_SECONDARY_SOURCES = {"coingecko", "alternative_me"}
_OTHER_ALERTS = {
    "COMPRAR AGORA": "entrou em tendência de alta",
    "VENDER AGORA": "saiu da tendência de alta",
    "NO RADAR": "chegou perto de voltar à tendência de alta",
    "SAIU DO RADAR": "saiu do radar",
}
_BAD_TOKEN = re.compile(r"\b(nan|inf|None)\b|<NA>|NaT")


def _num(x: float, digits: int = 2) -> str:
    return f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


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

OPPORTUNITY_TEXT = {"BOA_RELATIVA": "boa oportunidade relativa", "MODERADA": "oportunidade moderada"}
REGIME_TEXT = {
    "FAVORAVEL": "favorável — o Bitcoin está acima da média de 200 dias (tendência de longo prazo em alta)",
    "NEUTRO": "neutro — o Bitcoin está acima da média de 200 dias, mas a média de 50 dias ainda está abaixo dela",
    "DEFENSIVO": "defensivo — o Bitcoin está abaixo da média de 200 dias; a regra de risco não abre compras novas",
    "INDISPONIVEL": "sem dados confiáveis do Bitcoin (filtro de mercado)",
}
_REASON_TEXT = {
    "tendência de alta": "tendência de alta (acima da média de 200 dias)",
    "momento positivo": "momento positivo (subiu em 30 e 90 dias)",
    "tendência persistente": "tendência firme",
}
NO_OPPORTUNITY = (
    "Hoje não encontrei oportunidades suficientemente boas dentro dos critérios configurados. "
    "Aporte sugerido: R$ 0 de {budget}. O orçamento permanece sem alocação."
)
IMPORTANT = (
    "Importante: são estimativas quantitativas, não garantias de valorização. Score = nota relativa de 0 a 100 "
    "contra as outras moedas analisadas, não probabilidade de lucro. O orçamento é uma simulação para o valor "
    "informado: o sistema não acessa o seu saldo."
)


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None  # pd.NA e None viram None


def _brl(x: float) -> str:
    return f"R$ {_num(x, 0 if math.isclose(x, round(x)) else 2)}"


def _strings(value: object) -> list[str]:
    """Coluna de lista do Parquet (list, tupla ou array do numpy) como lista de str."""
    if isinstance(value, np.ndarray):
        return [str(v) for v in value.tolist()]
    if isinstance(value, list | tuple):
        return [str(v) for v in value]
    return []


@dataclass(frozen=True)
class Pick:
    """Uma moeda selecionada, com tipos explícitos (a entrada do formatador, sem Series do pandas)."""

    symbol: str
    opportunity: str
    score: float
    allocation_brl: float
    allocation_note: str | None
    reasons: tuple[str, ...]
    risks: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.symbol.split("/")[0]


def _picks(signals: pd.DataFrame) -> list[Pick]:
    chosen = signals[signals["selected"].fillna(False).astype(bool)].sort_values("candidate_rank")
    return [
        Pick(
            symbol=str(r["symbol"]),
            opportunity=str(r["opportunity"]),
            score=float(r["score"]),
            allocation_brl=float(r["allocation_brl"]),
            allocation_note=_opt_str(r["allocation_note"]),
            reasons=tuple(_strings(r["reasons"])),
            risks=tuple(_strings(r["risks"])),
        )
        for r in chosen.to_dict("records")
    ]


def _motive(reasons: Sequence[str]) -> str:
    labels = [_REASON_TEXT.get(t.split(":")[0], t.split(":")[0]) for t in reasons if "condições favoráveis" not in t]
    if not labels:
        return "passou em todos os filtros obrigatórios."
    items = labels[:3]
    joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]
    return joined[0].upper() + joined[1:] + "."


def _main_blockers(signals: pd.DataFrame, limit: int = 3) -> list[str]:
    """Os bloqueios mais frequentes entre as moedas analisadas (o motivo de não haver compra)."""
    counts: dict[str, int] = {}
    for value in signals["blockers"].tolist():
        for b in _strings(value):
            key = b.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [f"{k} ({v} de {len(signals)} moedas)" for k, v in ranked]


_MAX_LISTED = 40
STAGE_BUY_LABEL = "COMPRAR"
STAGE_UNAVAILABLE_LABEL = "INDISPONÍVEL"


def _tickers(symbols: Sequence[str]) -> str:
    names = sorted(str(s).split("/")[0] for s in symbols)
    extra = len(names) - _MAX_LISTED
    return ", ".join(names[:_MAX_LISTED]) + (f" e mais {extra}" if extra > 0 else "")


def _rule_state(signals: pd.DataFrame) -> str:
    """Estado da regra SMA 200 de cada moeda, separado do COMPRAR. COMPRAR só existe para moeda com evidência
    estatística validada (o pipeline já rebaixou as demais); a regra ativa nas outras é só descrição."""
    stage = signals["stage"].astype(str)
    buy = signals.loc[stage.eq(STAGE_BUY_LABEL), "symbol"].tolist()
    nodata = signals.loc[stage.eq(STAGE_UNAVAILABLE_LABEL), "symbol"].tolist()
    rest = signals[~stage.isin([STAGE_BUY_LABEL, STAGE_UNAVAILABLE_LABEL])]
    active = rest.loc[rest["uptrend"].fillna(False).astype(bool), "symbol"].tolist()
    inactive = rest.loc[~rest["uptrend"].fillna(False).astype(bool), "symbol"].tolist()
    lines = ["Regra SMA 200 por moeda (separada do COMPRAR)"]
    lines.append(
        f"Moedas com evidência estatística validada: {_tickers(buy)}." if buy
        else "Nenhuma moeda tem evidência estatística validada: não há sinal de COMPRAR."
    )
    if buy:
        lines.append(f"COMPRAR (evidência validada): {_tickers(buy)}")
    if active:
        lines.append(f"Regra ativa, sem evidência estatística: {_tickers(active)}")
    if inactive:
        lines.append(f"Regra inativa: {_tickers(inactive)}")
    if nodata:
        lines.append(f"Sem dado confiável hoje: {_tickers(nodata)}")
    return "\n".join(lines)


def format_report(
    signals: pd.DataFrame,
    recommendation: pd.DataFrame,
    *,
    now: pd.Timestamp,
    recommended: Sequence[str],
) -> list[str]:
    """Mensagens do dia (já divididas em até 4096 caracteres), só com números calculados pelo pipeline.

    `signals`: daily_signals da execução (recommendation.SIGNALS_SCHEMA). `recommendation`: a linha do resumo
    (RECOMMENDATION_SCHEMA). `recommended`: moedas da regra SMA 200, para os alertas de virada.
    """
    rec = recommendation.iloc[0]
    budget = float(rec["budget_brl"])
    local = now.tz_convert(FORTALEZA)
    expected = now.floor("D") - pd.Timedelta(days=1)
    data_day = pd.Timestamp(rec["data_day"])
    lag = int((expected - data_day).days) if pd.notna(data_day) else None

    head = ["📊 CRIPTO — ANÁLISE DO DIA", f"{local:%d/%m/%Y %H:%M} (Fortaleza) · {now:%d/%m %H:%M} UTC"]
    if lag is None:
        head.append("Dados: sem candles.")
    else:
        state = "em dia" if lag <= 0 else f"ATRASADO {lag} dia(s)"
        head.append(f"Dados: fechamento diário de {_day(data_day)} (UTC), {state}.")
    head.append(f"Orçamento disponível na simulação: {_brl(budget)}")
    head.append(f"Mercado: {REGIME_TEXT.get(str(rec['regime']), str(rec['regime']))}.")
    out = ["\n".join(head)]

    limits = _strings(rec["data_notes"])
    if lag is not None and lag > 0:
        limits.insert(0, "os candles estão atrasados: nenhuma moeda sem candle de ontem pode ser recomendada")
    if limits:
        out.append("⚠️ Limitações desta análise\n" + "\n".join(f"- {t}" for t in limits))

    picks = _picks(signals)
    total = float(rec["total_brl"])
    if not picks or total <= 0:
        why = _main_blockers(signals)
        lines = [NO_OPPORTUNITY.format(budget=_brl(budget))]
        if picks:  # havia candidatas, mas nenhum aporte executável
            lines.append("Havia candidatas, mas os valores ficariam impraticáveis:")
            lines += [f"- {p.name}: {p.allocation_note or 'sem aporte executável'}" for p in picks]
        elif why:
            lines.append("Principais motivos: " + "; ".join(why) + ".")
        out.append("\n".join(lines))
    else:
        block = ["Melhores oportunidades"]
        for i, p in enumerate(picks, start=1):
            block.append("")
            block.append(f"{i}. {p.name} — Aporte sugerido: {_brl(p.allocation_brl)}")
            block.append(f"Classificação: {OPPORTUNITY_TEXT.get(p.opportunity, p.opportunity)} (score {_num(p.score, 0)} de 100)")
            block.append(f"Motivo: {_motive(p.reasons)}")
            block.append("Atenção: " + (p.risks[0] if p.risks else "sem alerta de risco além da oscilação normal de cripto") + ".")
            if p.allocation_brl <= 0 and p.allocation_note:
                block.append(f"Sem aporte: {p.allocation_note}.")
        out.append("\n".join(block))
        summary = [
            "Resumo do aporte",
            f"Total sugerido: {_brl(total)} de {_brl(budget)}.",
            f"Saldo não alocado: {_brl(float(rec['unallocated_brl']))}.",
            f"Decisão: considerar um aporte de {_brl(total)}, ou aguardar, conforme as condições e os limites do modelo.",
        ]
        summary += _strings(rec["notes"])
        out.append("\n".join(summary))

    alerts: list[str] = []
    for r in signals[signals["symbol"].isin(list(recommended))].to_dict("records"):
        alert = _opt_str(r["alert"])
        if alert in _OTHER_ALERTS:
            alerts.append(f"{str(r['symbol']).split('/')[0]} {_OTHER_ALERTS[alert]} hoje (regra principal SMA 200).")
    panic = [str(s).split("/")[0] for s in signals.loc[signals["panic"].fillna(False).astype(bool), "symbol"]]
    if panic:
        alerts.append(f"Pânico em {', '.join(panic)}: queda forte com medo no mercado. É só aviso; comprar no pânico perdeu dinheiro nos testes.")
    if alerts:
        out.append("Alertas\n" + "\n".join(f"- {a}" for a in alerts))

    out.append(_rule_state(signals))
    out.append(f"Validação histórica: {rec['evidence']}")
    out.append(IMPORTANT + " Detalhes de cada moeda e do backtest no painel.")
    return split_message("\n\n".join(out))


def data_notes(available: pd.DataFrame, source_errors: pd.DataFrame | None) -> list[str]:
    """Limitações dos dados da execução, em frases curtas (para o resumo e o Telegram)."""
    notes: list[str] = []
    errors = source_errors if source_errors is not None else pd.DataFrame(columns=["source", "scope", "detail"])
    failed = [str(e.scope).split("/")[0] for e in errors.itertuples() if str(e.source) == "binance"]
    if failed:
        notes.append(f"falha na coleta de preços ({', '.join(failed)}): essas moedas não podem ser recomendadas hoje")
    secondary = sorted({str(e.source) for e in errors.itertuples() if str(e.source) in _SECONDARY_SOURCES})
    if secondary:
        notes.append(f"fonte secundária fora do ar ({', '.join(secondary)}): sem market cap e/ou humor do mercado; a análise usa só preço e volume")
    bad = available[~available["available"].astype(bool)]
    if not bad.empty:
        names = ", ".join(str(s).split("/")[0] for s in bad["symbol"])
        notes.append(f"{len(bad)} moeda(s) sem dado confiável hoje ({names}): ficam fora das recomendações")
    return notes


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
