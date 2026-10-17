"""Estatística pura compartilhada (CLAUDE.md §1): bootstrap em blocos e correção de Holm.

Fica fora de `policy_evaluation` para a produção (validação do COMPRAR) não importar módulos de pesquisa.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

NAN = float("nan")


def block_indices(n: int, block: int, resamples: int, rng: np.random.Generator) -> np.ndarray:
    """Índices (resamples × n) de um bootstrap em blocos circulares de tamanho `block`."""
    blocks = math.ceil(n / block)
    starts = rng.integers(0, n, size=(resamples, blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(resamples, blocks * block)[:, :n]


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Valores-p ajustados pelo método de Holm (controla a taxa de erro por família). NaN permanece NaN."""
    valid = [(p, i) for i, p in enumerate(p_values) if math.isfinite(p)]
    m = len(valid)
    out = [NAN] * len(p_values)
    running = 0.0
    for rank, (p, i) in enumerate(sorted(valid)):
        running = max(running, min(1.0, (m - rank) * p))
        out[i] = running
    return out
