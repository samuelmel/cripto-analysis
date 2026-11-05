"""Gera as figuras dos estudos (PNG) em docs/img/, em dois tamanhos: 1600x900 e 1080x1350.

Entrypoint (CLAUDE.md §1): lê Parquets de `evidence/` e `data/`, chama funções puras de preparação e só então desenha e salva.
Os números que só existem em tabelas de documentos (ΔSharpe, DCA) estão transcritos abaixo, com a fonte indicada.

    uv run python research/make_figures.py            # todas as figuras
    uv run python research/make_figures.py 04 05      # só as indicadas
"""

from __future__ import annotations

import math
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.renko_chart import renko  # noqa: E402
from src.transformers.bottom_confirmation import bias_summary  # noqa: E402

OUT_DIR = Path("docs/img")
EVIDENCE = Path("evidence")
BG = "#FAFAF7"
INK = "#1F2430"
MUTED = "#8A909C"
GRID = "#E3E3DD"
ACCENT = "#C2410C"  # única cor de destaque
SIZES: dict[str, tuple[float, float]] = {"16x9": (16.0, 9.0), "4x5": (10.8, 13.5)}  # polegadas a 100 dpi: 1600x900 e 1080x1350


# ---------------------------------------------------------------------------------------------
# Preparação dos dados (funções puras)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Interval:
    label: str
    value: float
    low: float
    high: float


# ΔSharpe contra comprar e segurar, IC de 90%, 2020-01-01 a 2026-10-15 (docs/pesquisa_quantitativa.md, "Resultado com dados reais").
SHARPE_DELTAS: tuple[Interval, ...] = (
    Interval("Seleção (aporte variável)", 0.71, 0.08, 1.23),
    Interval("Seleção, peso igual", 0.51, -0.11, 1.00),
    Interval("Tendência diária (todas)", 0.12, -0.37, 0.57),
    Interval("SMA 200 semanal", 0.11, -0.46, 0.63),
    Interval("Tendência (regra do painel)", 0.11, -0.37, 0.55),
    Interval("Tendência sem filtro do BTC", 0.07, -0.36, 0.49),
    Interval("Rompimento + volume", 0.06, -0.47, 0.50),
    Interval("Donchian", -0.07, -0.62, 0.36),
    Interval("Cruzamento SMA 50/200", -0.17, -0.65, 0.28),
    Interval("Momento 90 dias", -0.21, -0.81, 0.29),
    Interval("RSI sobrevendido", -0.69, -1.46, 0.05),
    Interval("Momento simples", -0.78, -1.31, -0.35),
    Interval("Bollinger", -1.09, -1.74, -0.51),
    Interval("Queda dentro da alta", -1.24, -2.15, -0.33),
)

# docs/dca_study.md, execução de 2026-11-03: Smart DCA (f = 0,5) contra DCA fixo, valor final por real aportado.
DCA_ROWS: tuple[tuple[str, float, int], ...] = (  # (janela, diferença média em %, % de vitórias)
    ("BTC · 3 anos", -2.58, 29),
    ("BTC · 5 anos", -3.16, 25),
    ("ETH · 3 anos", 1.02, 75),
    ("ETH · 5 anos", 0.90, 62),
)

AI_LABELS = {
    "G_GBM_SEM_FNG": "IA (boosting)",
    "F_LOGIT_SEM_FNG": "IA (logística)",
    "MOMENTO_90D": "Momento de 90 dias (referência)",
}


def significant(item: Interval) -> bool:
    return item.low > 0 or item.high < 0


def sma200_bars(table: pd.DataFrame) -> pd.DataFrame:
    """Queda máxima e volatilidade médias, comprar e segurar x SMA 200 (evidence/continuidade_v1/risk_sma200.parquet)."""
    names = {"max_drawdown": "Queda máxima", "volatility": "Oscilação anual"}
    rows = [
        {"metric": names[str(r["metric"])], "hold": float(r["mean_hold"]), "sma200": float(r["mean_strategy"]),
         "reduction": float(r["reduction"]), "ci_low": float(r["ci_low"]), "ci_high": float(r["ci_high"]),
         "n_coins": int(r["n_coins"]), "test_n_coins": int(r["test_n_coins"]), "test_reduction": float(r["test_reduction"])}
        for _, r in table.iterrows() if str(r["metric"]) in names
    ]
    return pd.DataFrame(rows)


def ai_intervals(ranking: pd.DataFrame) -> pd.DataFrame:
    """top 5 menos universo (30 dias), por modelo e período, em pontos percentuais."""
    sub = ranking[ranking["metric"].eq("top_k_vs_universo")
                  & ranking["model"].isin(AI_LABELS)
                  & ranking["period"].isin(["DESENVOLVIMENTO", "TESTE_FINAL"])].copy()
    for col in ("mean", "ci_low", "ci_high"):
        sub[col] = sub[col] * 100.0
    sub["label"] = sub["model"].map(AI_LABELS)
    return sub[["label", "period", "mean", "ci_low", "ci_high", "n_days"]].reset_index(drop=True)


def renko_series(ohlc: pd.DataFrame, pct: float) -> list[tuple[pd.Timestamp, float, float]]:
    return renko(ohlc["close"], pct)


def pt(value: float, digits: int = 1, sign: bool = False) -> str:
    text = f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"
    return text.replace(".", ",").replace("-", "−")


# ---------------------------------------------------------------------------------------------
# Desenho
# ---------------------------------------------------------------------------------------------

def start(size: str, title: str, subtitle: str, left: float | None = None) -> tuple[Figure, Axes, float]:
    """Figura com título que afirma a conclusão; devolve (figura, eixo, fator de escala da fonte)."""
    w, h = SIZES[size]
    portrait = size == "4x5"
    fig = plt.figure(figsize=(w, h), dpi=100, facecolor=BG)
    wrap_title = 30 if portrait else 58
    wrap_sub = 62 if portrait else 112
    title_lines = textwrap.wrap(title, wrap_title)
    sub_lines = textwrap.wrap(subtitle, wrap_sub)
    fig.text(0.06, 0.965, "\n".join(title_lines), fontsize=33 if portrait else 31, fontweight="bold",
             color=INK, va="top", ha="left", linespacing=1.15)
    title_h = len(title_lines) * (0.042 if portrait else 0.062)
    fig.text(0.06, 0.965 - title_h - 0.012, "\n".join(sub_lines), fontsize=15 if portrait else 14.5, color=MUTED,
             va="top", ha="left", linespacing=1.35)
    sub_h = len(sub_lines) * (0.021 if portrait else 0.031)
    top = 0.965 - title_h - sub_h - 0.05
    x0 = left if left is not None else (0.09 if not portrait else 0.10)
    bottom = 0.19 if not portrait else 0.13
    ax = fig.add_axes((x0, bottom, 0.97 - x0, max(top - bottom, 0.3)))
    ax.set_facecolor(BG)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=15)
    return fig, ax, 1.0


def footer(fig: Figure, text: str) -> None:
    fig.text(0.06, 0.018, text, fontsize=11.5, color=MUTED, va="bottom", ha="left")


def finish(fig: Figure, name: str, size: str, source: str) -> Path:
    sep = "\n" if size == "4x5" else "  ·  "
    footer(fig, source + sep + "Pesquisa educacional, não é recomendação de investimento.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}_{size}.png"
    fig.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)
    return path


def forest(ax: Axes, items: list[tuple[str, float, float, float, bool]], unit: str, digits: int = 2) -> None:
    """Pontos com intervalo; destaca (cor de destaque) os que têm intervalo fora de zero."""
    for i, (label, value, low, high, highlight) in enumerate(reversed(items)):
        color = ACCENT if highlight else MUTED
        ax.plot([low, high], [i, i], color=color, linewidth=3.2, solid_capstyle="round")
        ax.plot([value], [i], marker="o", markersize=9, color=color)
    ax.set_yticks(range(len(items)))
    ax.set_yticklabels([it[0] for it in reversed(items)], fontsize=15)
    ax.axvline(0, color=INK, linewidth=1.4)
    ax.xaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_xlabel(unit, fontsize=14, color=MUTED)
    ax.set_ylim(-0.7, len(items) - 0.3)
    ax.tick_params(axis="y", length=0)
    _ = digits


def fig_sharpe(size: str) -> Path:
    fig, ax, _ = start(size, "Quase nenhuma estratégia vence comprar e segurar",
                       "Diferença de Sharpe contra comprar e segurar, com intervalo de confiança de 90% (2020 a 2026). "
                       "À direita de zero = melhor que segurar. Em laranja: o intervalo não inclui zero. "
                       "A Seleção, única à frente, não resistiu à correção para testes múltiplos (Holm 0,27).",
                       left=0.30 if size == "16x9" else 0.40)
    items = [(s.label, s.value, s.low, s.high, significant(s)) for s in SHARPE_DELTAS]
    forest(ax, items, "ΔSharpe (maior é melhor)")
    return finish(fig, "01_estrategias_vs_segurar", size, "Fonte: docs/pesquisa_quantitativa.md · histórico já explorado")


def fig_sma200(size: str) -> Path:
    table = sma200_bars(pd.read_parquet(EVIDENCE / "continuidade_v1" / "risk_sma200.parquet"))
    n = int(table["n_coins"].iloc[0])
    fig, ax, _ = start(size, "A média de 200 dias reduziu as quedas",
                       f"Média de {n} moedas, 2017 a 2024. “Média de 200 dias” = ficar em dinheiro quando o preço está abaixo "
                       "da média dos últimos 200 dias. Nos dados de 2025 em diante a redução se repetiu.")
    width = 0.36
    xs = list(range(len(table)))
    ax.bar([x - width / 2 for x in xs], table["hold"] * 100, width, color=MUTED, label="Só segurar")
    ax.bar([x + width / 2 for x in xs], table["sma200"] * 100, width, color=ACCENT, label="Com a média de 200 dias")
    for x, row in zip(xs, table.itertuples(), strict=True):
        ax.text(x - width / 2, row.hold * 100 + 1.5, f"{row.hold * 100:.0f}%".replace(".", ","), ha="center", fontsize=17, color=INK)
        ax.text(x + width / 2, row.sma200 * 100 + 1.5, f"{row.sma200 * 100:.0f}%".replace(".", ","), ha="center", fontsize=17,
                color=ACCENT, fontweight="bold")
        ax.text(x, -14, f"menos {row.reduction * 100:.0f} pontos (IC 95%: {row.ci_low * 100:.0f} a {row.ci_high * 100:.0f})",
                ha="center", fontsize=13, color=INK)
    ax.set_xticks(xs)
    ax.set_xticklabels(table["metric"], fontsize=18)
    ax.set_ylim(-20, max(table["hold"].max() * 100 * 1.18, 100))
    ax.set_ylabel("%", fontsize=14, color=MUTED)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=15, loc="upper right")
    return finish(fig, "02_media_200_dias", size, "Fonte: docs/sma200_risk.md · evidence/continuidade_v1/risk_sma200.parquet")


def fig_ai(size: str) -> Path:
    data = ai_intervals(pd.read_parquet(EVIDENCE / "ml_study_v2" / "ranking.parquet"))
    fig, ax, _ = start(size, "As 5 escolhas da IA ainda não provaram vencer o acaso",
                       "Retorno em 30 dias das 5 moedas mais bem ranqueadas menos o do conjunto todo, em pontos percentuais, "
                       "com IC de 95%. A IA ordena melhor que o acaso, mas escolher só 5 rende pouco.",
                       left=0.30 if size == "16x9" else 0.38)
    items: list[tuple[str, float, float, float, bool]] = []
    for label in AI_LABELS.values():
        for period, tag in (("DESENVOLVIMENTO", "2020–24"), ("TESTE_FINAL", "2025+")):
            r = data[data["label"].eq(label) & data["period"].eq(period)]
            if r.empty:
                continue
            row = r.iloc[0]
            low, high = float(row["ci_low"]), float(row["ci_high"])
            items.append((f"{label}\n{tag}", float(row["mean"]), low, high, label.startswith("IA")))
    forest(ax, items, "Diferença para o conjunto (pontos percentuais; maior é melhor)")
    ax.text(0.99, 0.02, "Só o desenvolvimento (2020–24) decide;\no teste final (622 dias) só pode contradizer.",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=13.5, color=INK)
    return finish(fig, "03_ia_vs_acaso", size, "Fonte: docs/ml_study_v2.md · evidence/ml_study_v2/ranking.parquet")


def fig_bottom(size: str) -> Path:
    trades = pd.read_parquet(EVIDENCE / "bottom_confirmation" / "trades.parquet")
    bars = bias_summary(trades, hold=10, lookback=20)
    n_trades = f"{int(bars['n_trades'].iloc[0]):,}".replace(",", ".")
    fig, ax, _ = start(size, "Comprar “no fundo” só funciona se você souber o futuro",
                       "Regra: o preço fecha na mínima de 20 dias e os 2 dias seguintes fecham em alta. Retorno médio por operação, "
                       f"segurando 10 dias, 32 moedas, {n_trades} operações, já descontado o custo de 0,2%.")
    labels = ["Com viés\n(compra no fundo,\nsem saber ainda)", "Honesta\n(compra depois\nde confirmar)", "Acaso\n(compra num\ndia qualquer)"]
    colors = [ACCENT, MUTED, MUTED]
    values = (bars["mean_return"] * 100).tolist()
    ax.bar(range(3), values, color=colors, width=0.58)
    for i, v in enumerate(values):
        ax.text(i, v + 0.25, pt(v, 1, sign=True) + "%", ha="center", fontsize=26, fontweight="bold", color=colors[i])
    ax.set_xticks(range(3))
    ax.set_xticklabels(labels, fontsize=15)
    ax.set_ylim(0, max(values) * 1.18)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_ylabel("% por operação", fontsize=14, color=MUTED)
    ax.text(0.99, 0.62, "A barra laranja é uma ilusão:\nela usa um preço que ninguém\nconseguiria pegar na hora.",
            transform=ax.transAxes, ha="right", fontsize=15, color=INK)
    return finish(fig, "04_ilusao_do_fundo", size, "Fonte: docs/fundo_confirmado.md · evidence/bottom_confirmation/")


def fig_dca(size: str) -> Path:
    fig, ax, _ = start(size, "DCA inteligente: perde no BTC e só empata no ETH",
                       "Diferença no valor final por real aportado, DCA “inteligente” (compra mais nas quedas) menos DCA de valor fixo. "
                       "Acima de zero = o inteligente ganhou. Diferenças pequenas, poucas janelas.")
    values = [r[1] for r in DCA_ROWS]
    colors = [ACCENT if v < 0 else MUTED for v in values]
    ax.bar(range(len(DCA_ROWS)), values, color=colors, width=0.58)
    for i, (_, v, wins) in enumerate(DCA_ROWS):
        ax.text(i, v + (0.18 if v >= 0 else -0.18), pt(v, 2, sign=True) + "%", ha="center", va="bottom" if v >= 0 else "top",
                fontsize=22, fontweight="bold", color=colors[i])
        ax.text(i, -4.15, f"ganhou em {wins}%\ndas janelas", ha="center", va="top", fontsize=14, color=INK)
    ax.axhline(0, color=INK, linewidth=1.4)
    ax.set_xticks(range(len(DCA_ROWS)))
    ax.set_xticklabels([r[0] for r in DCA_ROWS], fontsize=16)
    ax.xaxis.set_ticks_position("top")
    ax.set_ylim(-5.4, 2.6)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_ylabel("% do valor final", fontsize=14, color=MUTED)
    return finish(fig, "05_dca_inteligente", size, "Fonte: docs/dca_study.md · 3 e 5 anos, execução de 2026-11-03")


def fig_renko(size: str) -> Path:
    candles = pd.read_parquet("data/market/ohlcv_1d/symbol=BTC_USDT")
    ohlc = candles.sort_values("timestamp").set_index("timestamp")
    bricks = renko_series(ohlc, 5.0)
    fig, ax, _ = start(size, "O gráfico Renko do BTC é limpo, mas não venceu comprar e segurar",
                       "Cada tijolo = 5% de variação do preço (escala logarítmica), sem eixo de tempo. Nos testes com 7 moedas, "
                       "só 21% a 43% das regras Renko bateram comprar e segurar (critério era 50%).")
    for i, (_, base, top) in enumerate(bricks):
        up = top > base
        lo, hi = math.exp(min(base, top)), math.exp(max(base, top))
        ax.add_patch(Rectangle((i, lo), 1.0, hi - lo, facecolor=ACCENT if up else MUTED, edgecolor="none"))
    ax.set_xlim(0, len(bricks))
    lows = [math.exp(min(b, t)) for _, b, t in bricks]
    highs = [math.exp(max(b, t)) for _, b, t in bricks]
    ax.set_ylim(min(lows) * 0.9, max(highs) * 1.1)
    ax.set_yscale("log")
    ax.set_xlabel("tijolos (laranja = alta, cinza = queda)", fontsize=14, color=MUTED)
    ax.set_ylabel("preço do BTC (US$)", fontsize=14, color=MUTED)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    return finish(fig, "06_renko_btc", size, "Fonte: docs/renko_estudo.md · candles diários da Binance (2017 em diante)")


BUILDERS: dict[str, Callable[[str], Path]] = {
    "01": fig_sharpe, "02": fig_sma200, "03": fig_ai, "04": fig_bottom, "05": fig_dca, "06": fig_renko,
}


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    chosen = argv or list(BUILDERS)
    for key in chosen:
        for size in SIZES:
            print(BUILDERS[key](size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
