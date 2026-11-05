"""Mensagem curta e simples do Telegram (padrão): uma única mensagem, em português sem jargão.

Função pura: dados entram, lista de textos sai. O formato detalhado continua em `notification.format_report` e é ativado
pelo entrypoint (variável `TELEGRAM_DETALHADO=1`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

from src.transformers.notification import FORTALEZA, _picks

SHORT_LIMIT = 600
MAX_COINS = 3

REGIME_FAVORABLE = "FAVORAVEL"
REGIME_NEUTRAL = "NEUTRO"
REGIME_DEFENSIVE = "DEFENSIVO"

MARKET_TEXT = {
    REGIME_FAVORABLE: "em alta 🟢",
    REGIME_NEUTRAL: "indefinido 🟡",
    REGIME_DEFENSIVE: "em baixa 🔴",
}
MARKET_UNAVAILABLE = "sem dados ⚪"
REGIME_CHANGE_TEXT = {
    REGIME_FAVORABLE: "o mercado virou para alta",
    REGIME_NEUTRAL: "o mercado ficou indefinido",
    REGIME_DEFENSIVE: "o mercado virou para baixa",
}
# Carteira simulada -> nome em português simples (a IA fica marcada como em teste).
WALLET_NAMES: Mapping[str, str] = {"PAINEL": "Regra", "IA": "IA (em teste)", "SO_BTC": "Só segurar BTC"}
FOOTER = "Detalhes no painel. Simulação, não é recomendação."


def _signed(value: float) -> str:
    return f"{value:+.1f}%".replace(".", ",").replace("-", "−")


def _market_line(rec: Mapping[str, object]) -> str:
    regime = str(rec.get("regime", ""))
    text = MARKET_TEXT.get(regime, MARKET_UNAVAILABLE)
    close, sma = rec.get("regime_close"), rec.get("regime_sma_200")
    if isinstance(close, int | float) and isinstance(sma, int | float) and math.isfinite(close) and math.isfinite(sma) and sma > 0:
        gap = (close / sma - 1.0) * 100.0
        where = "acima" if gap >= 0 else "abaixo"
        return f"Mercado: {text} (BTC {abs(gap):.0f}% {where} da média de 200 dias)".replace(".", ",")
    return f"Mercado: {text}"


def _today_line(signals: pd.DataFrame, total_brl: float, max_coins: int) -> str:
    names = [p.name for p in _picks(signals) if p.allocation_brl > 0]
    if total_brl <= 0 or not names:
        return "Hoje: nada a fazer"
    shown = ", ".join(names[:max_coins])
    more = f" e mais {len(names) - max_coins}" if len(names) > max_coins else ""
    amount = f"R$ {total_brl:.0f}" if math.isclose(total_brl, round(total_brl)) else f"R$ {total_brl:.2f}".replace(".", ",")
    return f"Hoje: aporte simulado de {amount} em {shown}{more}"


def _wallets_line(summary: pd.DataFrame | None, *, since_start: bool) -> str | None:
    if summary is None or summary.empty:
        return None
    parts = []
    for wallet, name in WALLET_NAMES.items():
        row = summary[summary["wallet"].eq(wallet)]
        if row.empty:
            continue
        value = float(row["return_pct"].iloc[0])
        if math.isfinite(value):
            parts.append(f"{name} {_signed(value)}")
    if not parts:
        return None
    head = "Carteiras simuladas (desde o início)" if since_start else "Carteiras simuladas"
    return f"{head}: " + " · ".join(parts)


def _changes(rec: Mapping[str, object], previous_regime: str | None, lag_days: int | None, n_position_changes: int,
             n_entry_changes: int) -> list[str]:
    """Avisos extras: só o que MUDOU desde ontem (mais o atraso dos dados, que afeta a confiança de tudo)."""
    out: list[str] = []
    regime = str(rec.get("regime", ""))
    if previous_regime and previous_regime != regime and regime in REGIME_CHANGE_TEXT:
        out.append(f"⚠️ Mudou: {REGIME_CHANGE_TEXT[regime]}.")
    if n_position_changes > 0:
        out.append("⚠️ Mudou: uma posição sua mudou de estado (veja no painel).")
    if n_entry_changes > 0:
        out.append("⚠️ Mudou: apareceu um novo sinal de entrada (veja no painel).")
    if lag_days is not None and lag_days > 0:
        out.append(f"⚠️ Dados atrasados {lag_days} dia(s).")
    return out


def format_short_report(
    signals: pd.DataFrame,
    recommendation: pd.DataFrame,
    *,
    now: pd.Timestamp,
    sim_summary: pd.DataFrame | None = None,
    previous_regime: str | None = None,
    n_position_changes: int = 0,
    n_entry_changes: int = 0,
    ai_line: str | None = None,
) -> list[str]:
    """Uma única mensagem de até `SHORT_LIMIT` caracteres: mercado, o que fazer hoje, placar das carteiras simuladas e,
    só se algo mudou desde ontem, os avisos. `ai_line` (opcional) é a opinião/estado da IA, já em texto simples.

    Se passar do limite, encurta por etapas (menos moedas, sem avisos opcionais) em vez de dividir em várias mensagens.
    """
    rec = {str(k): v for k, v in recommendation.iloc[0].to_dict().items()}
    local = now.tz_convert(FORTALEZA)
    expected = now.floor("D") - pd.Timedelta(days=1)
    data_day = pd.Timestamp(rec["data_day"]) if pd.notna(rec.get("data_day")) else None
    lag = int((expected - data_day).days) if data_day is not None else None
    total = float(str(rec.get("total_brl", 0.0)))

    def build(max_coins: int, since_start: bool, with_ai: bool) -> str:
        lines = [f"📊 Cripto hoje ({local:%d/%m})", _market_line(rec), _today_line(signals, total, max_coins)]
        wallets = _wallets_line(sim_summary, since_start=since_start)
        if wallets:
            lines.append(wallets)
        if ai_line and with_ai:
            lines.append(ai_line)
        lines += _changes(rec, previous_regime, lag, n_position_changes, n_entry_changes)
        lines.append(FOOTER)
        return "\n".join(lines)

    for max_coins, since_start, with_ai in ((MAX_COINS, True, True), (MAX_COINS, False, True), (2, False, True), (1, False, False)):
        text = build(max_coins, since_start, with_ai)
        if len(text) <= SHORT_LIMIT:
            return [text]
    return [text[: SHORT_LIMIT - 1] + "…"]
