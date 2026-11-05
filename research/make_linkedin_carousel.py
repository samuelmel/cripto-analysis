"""Monta o carrossel do LinkedIn (PDF, 8 slides de 1080x1350) com as figuras de docs/img/ e slides de texto.

Entrypoint (CLAUDE.md §1): só lê PNGs, desenha e grava `linkedin/carrossel.pdf` (pasta fora do repositório público).
Rode antes `research/make_figures.py`.

    uv run python research/make_linkedin_carousel.py [pasta_para_png_dos_slides]
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

IMG = Path("docs/img")
OUT = Path("linkedin/carrossel.pdf")
REPO = "github.com/samuelmel/cripto-analysis"
BG, INK, MUTED, ACCENT = "#FAFAF7", "#1F2430", "#8A909C", "#C2410C"
SIZE = (10.8, 13.5)  # polegadas a 100 dpi = 1080x1350

FIGURE_SLIDES = ("01_estrategias_vs_segurar_4x5.png", "04_ilusao_do_fundo_4x5.png", "02_media_200_dias_4x5.png",
                 "03_ia_vs_acaso_4x5.png")


def text_slide(title: str, lines: list[str], *, kicker: str = "", footer: str = "") -> Image.Image:
    fig = plt.figure(figsize=SIZE, dpi=100, facecolor=BG)
    y = 0.90
    if kicker:
        fig.text(0.08, y, kicker.upper(), fontsize=20, color=ACCENT, fontweight="bold", va="top")
        y -= 0.05
    wrapped = textwrap.wrap(title, 19)
    fig.text(0.08, y, "\n".join(wrapped), fontsize=50, fontweight="bold", color=INK, va="top", linespacing=1.12)
    y -= 0.075 * len(wrapped) + 0.04
    for line in lines:
        parts = textwrap.wrap(line, 38)
        fig.text(0.08, y, "•", fontsize=28, color=ACCENT, va="top")
        fig.text(0.12, y, "\n".join(parts), fontsize=28, color=INK, va="top", linespacing=1.3)
        y -= 0.045 * len(parts) + 0.035
    if footer:
        fig.text(0.08, 0.05, "\n".join(textwrap.wrap(footer, 62)), fontsize=17, color=MUTED, va="bottom", linespacing=1.4)
    fig.canvas.draw()
    image = Image.frombuffer("RGBA", fig.canvas.get_width_height(), bytes(fig.canvas.buffer_rgba()), "raw", "RGBA", 0, 1)
    plt.close(fig)
    return image.convert("RGB")


def build_slides() -> list[Image.Image]:
    disclaimer = "Pesquisa educacional. Não é recomendação de investimento."
    slides = [
        text_slide("Tentei vencer o mercado de cripto com método científico", [
            "Cinco estudos, um pipeline em Python e uma conclusão incômoda.",
            "Deslize para ver o que os dados disseram.",
        ], kicker="Pesquisa quantitativa", footer=disclaimer),
        text_slide("O problema: todo backtest bonito pode ser sorte", [
            "Se você testa 100 ideias, umas 5 parecem boas só por acaso.",
            "É fácil, sem querer, usar uma informação que só existiria no futuro.",
            "Confundir sorte com habilidade custa dinheiro de verdade.",
        ], kicker="Por que desconfiar"),
        text_slide("O método: protocolo antes, resultado depois", [
            "A regra e o critério são escritos antes de rodar o teste.",
            "Tudo é comparado com comprar e segurar e com o acaso.",
            "Intervalo de confiança e correção para testes múltiplos.",
            "Custos reais e um período final separado só para contradizer.",
        ], kicker="Como testei"),
        *(Image.open(IMG / name).convert("RGB").resize((1080, 1350)) for name in FIGURE_SLIDES),
        text_slide("Conclusão: quase nada vence comprar e segurar", [
            "A média de 200 dias reduziu as quedas, mas não prometo mais lucro.",
            "Comprar no fundo só funciona se você souber o futuro.",
            "O que mais aprendi: desconfiar do meu próprio backtest.",
            f"Código aberto e estudos: {REPO}",
        ], kicker="O que fica", footer=disclaimer),
    ]
    assert len(slides) == 8
    return slides


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    slides = build_slides()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    slides[0].save(OUT, "PDF", resolution=100.0, save_all=True, append_images=slides[1:])
    print(f"{OUT} ({len(slides)} slides de 1080x1350)")
    if argv:
        folder = Path(argv[0])
        folder.mkdir(parents=True, exist_ok=True)
        for i, slide in enumerate(slides, start=1):
            slide.save(folder / f"slide_{i}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
