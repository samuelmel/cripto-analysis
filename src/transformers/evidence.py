"""Classificação da evidência de cada estratégia, por critérios fixados antes de olhar os resultados.

Puro (CLAUDE.md §1).

Categorias (a primeira que se aplica):
    INVALIDA                    problema de dado ou de método (feature ausente, livros que não fecham, motor
                                diferente): o teste não diz nada
    EVIDENCIA_INSUFICIENTE      amostra abaixo do mínimo de elegibilidade, OU diferença positiva mas compatível com
                                sorte (o intervalo da diferença de Sharpe contra a referência inclui zero)
    NEGATIVA                    diferença de Sharpe <= 0: não supera a referência das mesmas moedas (marcada como
                                "significativamente inferior" quando o intervalo inteiro fica abaixo de zero)
    PROMISSORA_NAO_CONFIRMADA   intervalo da diferença acima de zero, mas algum outro critério falhou (correção
                                para comparações múltiplas, estabilidade entre janelas, sensibilidade a custos,
                                atraso, posição inicial, deslistagem, parâmetros, retorno ou queda)
    ROBUSTA_NO_PROTOCOLO        TODOS os critérios abaixo atendidos

Critérios (`EvidenceCriteria`), todos exigidos para ROBUSTA_NO_PROTOCOLO:
    1. elegibilidade: n >= min_obs dias fora da amostra e, para estratégias de timing, >= min_entries entradas.
       É condição mínima para o teste ter sentido, NÃO prova de significância;
    2. p-valor ajustado por Holm < alpha na família pré-registrada;
    3. limite inferior do intervalo da diferença de Sharpe > 0;
    4. diferença de Sharpe > 0 em pelo menos `min_positive_fold_share` das janelas walk-forward;
    5. diferença de Sharpe > 0 em TODOS os cenários de estresse (custo alto, atraso, início em caixa, deslistagem,
       dados parciais);
    6. diferença de Sharpe > 0 em pelo menos `min_positive_variant_share` das variações moderadas de parâmetro
       (critério não avaliado = não atendido);
    7. retorno anualizado líquido > 0 e pior queda não mais funda que a da referência.
Mesmo ROBUSTA_NO_PROTOCOLO é sobre um histórico JÁ EXPLORADO no desenvolvimento: falta a confirmação prospectiva.
Nenhuma categoria promete retorno futuro.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

CATEGORY_INVALID = "INVALIDA"
CATEGORY_INSUFFICIENT = "EVIDENCIA_INSUFICIENTE"
CATEGORY_NEGATIVE = "NEGATIVA"
CATEGORY_PROMISING = "PROMISSORA_NAO_CONFIRMADA"
CATEGORY_ROBUST = "ROBUSTA_NO_PROTOCOLO"
CATEGORIES: tuple[str, ...] = (CATEGORY_INVALID, CATEGORY_INSUFFICIENT, CATEGORY_NEGATIVE, CATEGORY_PROMISING, CATEGORY_ROBUST)


@dataclass(frozen=True)
class EvidenceCriteria:
    alpha: float = 0.05
    min_obs: int = 730                 # 2 anos de dias fora da amostra
    min_entries: int = 10              # entradas, só para estratégias de timing
    min_positive_fold_share: float = 2 / 3
    min_positive_variant_share: float = 2 / 3

    def __post_init__(self) -> None:
        if not 0 < self.alpha < 1 or self.min_obs < 1 or self.min_entries < 0:
            raise ValueError("critérios de evidência inválidos")


@dataclass(frozen=True)
class EvidenceInput:
    invalid_reason: str | None
    n_obs: int
    n_entries: int
    timing: bool                       # estratégia de timing (exige número mínimo de entradas)
    delta_sharpe: float
    ci_low: float
    ci_high: float
    p_holm: float
    positive_fold_share: float
    stress_min_delta: float            # menor diferença de Sharpe entre os cenários de estresse (NaN = não avaliado)
    variant_positive_share: float      # fração das variações de parâmetro com diferença > 0 (NaN = não avaliado)
    cagr_pct: float
    max_drawdown_pct: float
    benchmark_max_drawdown_pct: float


def _ok(x: float) -> bool:
    return math.isfinite(x)


def classify(e: EvidenceInput, c: EvidenceCriteria = EvidenceCriteria()) -> tuple[str, list[str]]:
    """(categoria, motivos). Os motivos listam o que falhou (ou o que sustenta a categoria)."""
    if e.invalid_reason:
        return CATEGORY_INVALID, [e.invalid_reason]
    short: list[str] = []
    if e.n_obs < c.min_obs:
        short.append(f"amostra curta: {e.n_obs} dias (mínimo {c.min_obs})")
    if e.timing and e.n_entries < c.min_entries:
        short.append(f"poucas entradas: {e.n_entries} (mínimo {c.min_entries})")
    if not _ok(e.delta_sharpe):
        short.append("diferença de Sharpe não calculável")
    if short:
        return CATEGORY_INSUFFICIENT, short
    if e.delta_sharpe <= 0:
        tag = "significativamente inferior à referência" if _ok(e.ci_high) and e.ci_high < 0 else "não supera a referência"
        return CATEGORY_NEGATIVE, [f"{tag} (diferença de Sharpe {e.delta_sharpe:+.2f})"]
    if not (_ok(e.ci_low) and e.ci_low > 0):
        return CATEGORY_INSUFFICIENT, ["diferença positiva compatível com sorte: o intervalo inclui zero"]

    failed: list[str] = []
    if not (_ok(e.p_holm) and e.p_holm < c.alpha):
        failed.append(f"não sobrevive à correção de Holm (p ajustado {e.p_holm:.3f} >= {c.alpha})")
    if not (_ok(e.positive_fold_share) and e.positive_fold_share >= c.min_positive_fold_share):
        failed.append(f"instável entre janelas: positiva em {e.positive_fold_share:.0%} delas")
    if not (_ok(e.stress_min_delta) and e.stress_min_delta > 0):
        failed.append("sensível às premissas: algum cenário de estresse zera ou inverte a vantagem"
                      if _ok(e.stress_min_delta) else "cenários de estresse não avaliados")
    if not (_ok(e.variant_positive_share) and e.variant_positive_share >= c.min_positive_variant_share):
        failed.append("sensível aos parâmetros" if _ok(e.variant_positive_share) else "variações de parâmetro não avaliadas")
    if not (_ok(e.cagr_pct) and e.cagr_pct > 0):
        failed.append("retorno anualizado líquido não é positivo")
    if not (_ok(e.max_drawdown_pct) and _ok(e.benchmark_max_drawdown_pct) and e.max_drawdown_pct >= e.benchmark_max_drawdown_pct):
        failed.append("pior queda mais funda que a da referência")
    if failed:
        return CATEGORY_PROMISING, failed
    return CATEGORY_ROBUST, ["todos os critérios do protocolo atendidos no histórico explorado; falta confirmação prospectiva"]
