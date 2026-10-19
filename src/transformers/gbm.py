"""Gradient boosting de árvores para classificação binária, em NumPy puro e determinístico (sem scikit-learn).

Puro (CLAUDE.md §1). Boosting de Newton sobre a log-verossimilhança (como o XGBoost, versão mínima):
    1. começa do log-odds da taxa de positivos do TREINO;
    2. a cada rodada, gradiente g = p − y e hessiana h = p(1 − p);
    3. uma árvore de profundidade `max_depth` escolhe, em cada nó, o corte (feature, faixa) de maior ganho
       G_E²/(H_E + λ) + G_D²/(H_D + λ) − G²/(H + λ), com pelo menos `min_leaf` linhas de cada lado;
    4. folha = −G/(H + λ); o escore soma `learning_rate` × folha.
As faixas de corte são quantis de cada feature calculados SÓ no treino (`n_bins`), congelados para a previsão. Sem
aleatoriedade (nenhuma amostragem de linhas ou colunas): a mesma entrada dá sempre o mesmo modelo. Empate de ganho: a
primeira feature e a primeira faixa.

Hiperparâmetros fixos (`GBMParams`), escolhidos antes de ver resultado (docs/ml_study.md); nenhum ajuste por dobra.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Floats = NDArray[np.float64]
Ints = NDArray[np.int64]


@dataclass(frozen=True)
class GBMParams:
    n_rounds: int = 200
    learning_rate: float = 0.05
    max_depth: int = 3
    n_bins: int = 32
    min_leaf: int = 200
    l2: float = 1.0

    def __post_init__(self) -> None:
        if self.n_rounds < 1 or not 0 < self.learning_rate <= 1 or self.max_depth < 1:
            raise ValueError("n_rounds >= 1, learning_rate em (0, 1], max_depth >= 1")
        if self.n_bins < 2 or self.min_leaf < 1 or self.l2 < 0:
            raise ValueError("n_bins >= 2, min_leaf >= 1, l2 >= 0")


@dataclass(frozen=True)
class Tree:
    feature: Ints      # −1 = folha
    bin_cut: Ints      # vai à esquerda se faixa <= bin_cut
    left: Ints
    right: Ints
    value: Floats      # valor da folha (0 nos nós internos)


@dataclass(frozen=True)
class GBMModel:
    edges: tuple[Floats, ...]   # limites das faixas de cada feature (do treino)
    base_score: float
    trees: tuple[Tree, ...]
    params: GBMParams


def _sigmoid(z: Floats) -> Floats:
    out: Floats = 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))
    return out


def bin_edges(x: Floats, n_bins: int) -> tuple[Floats, ...]:
    """Quantis internos (sem repetição) de cada coluna: até n_bins − 1 limites."""
    qs = np.linspace(0.0, 1.0, n_bins + 1)[1:-1]
    return tuple(np.unique(np.quantile(x[:, j], qs)).astype("float64") for j in range(x.shape[1]))


def digitize(x: Floats, edges: tuple[Floats, ...]) -> Ints:
    """Faixa de cada valor (0 .. len(edges_j)), com os limites congelados do treino."""
    return np.column_stack([np.searchsorted(edges[j], x[:, j], side="right") for j in range(x.shape[1])]).astype(np.int64)


def _best_split(b: Ints, g: Floats, h: Floats, idx: Ints, n_bins: int, p: GBMParams) -> tuple[int, int, float]:
    gs, hs = float(g[idx].sum()), float(h[idx].sum())
    parent = gs * gs / (hs + p.l2)
    best = (-1, -1, 0.0)
    for j in range(b.shape[1]):
        col = b[idx, j]
        g_hist = np.bincount(col, weights=g[idx], minlength=n_bins)
        h_hist = np.bincount(col, weights=h[idx], minlength=n_bins)
        c_hist = np.bincount(col, minlength=n_bins)
        gl, hl, cl = np.cumsum(g_hist)[:-1], np.cumsum(h_hist)[:-1], np.cumsum(c_hist)[:-1]
        gr, hr, cr = gs - gl, hs - hl, len(idx) - cl
        ok = (cl >= p.min_leaf) & (cr >= p.min_leaf)
        if not ok.any():
            continue
        gain = gl * gl / (hl + p.l2) + gr * gr / (hr + p.l2) - parent
        gain = np.where(ok, gain, -np.inf)
        t = int(np.argmax(gain))
        if gain[t] > best[2] + 1e-12:
            best = (j, t, float(gain[t]))
    return best


def _grow(b: Ints, g: Floats, h: Floats, n_bins: int, p: GBMParams) -> Tree:
    feature: list[int] = []
    cut: list[int] = []
    left: list[int] = []
    right: list[int] = []
    value: list[float] = []

    def node(idx: Ints, depth: int) -> int:
        k = len(feature)
        feature.append(-1)
        cut.append(-1)
        left.append(-1)
        right.append(-1)
        value.append(0.0)
        j, t, gain = (-1, -1, 0.0) if depth >= p.max_depth else _best_split(b, g, h, idx, n_bins, p)
        if j < 0 or gain <= 0:
            value[k] = -float(g[idx].sum()) / (float(h[idx].sum()) + p.l2)
            return k
        go_left = b[idx, j] <= t
        feature[k], cut[k] = j, t
        left[k] = node(idx[go_left], depth + 1)
        right[k] = node(idx[~go_left], depth + 1)
        return k

    node(np.arange(len(g), dtype=np.int64), 0)
    return Tree(np.array(feature, dtype=np.int64), np.array(cut, dtype=np.int64), np.array(left, dtype=np.int64),
                np.array(right, dtype=np.int64), np.array(value, dtype="float64"))


def _tree_output(tree: Tree, b: Ints) -> Floats:
    pos = np.zeros(len(b), dtype=np.int64)
    for _ in range(len(tree.feature)):
        f = tree.feature[pos]
        internal = f >= 0
        if not internal.any():
            break
        rows = np.flatnonzero(internal)
        go_left = b[rows, f[rows]] <= tree.bin_cut[pos[rows]]
        pos[rows] = np.where(go_left, tree.left[pos[rows]], tree.right[pos[rows]])
    out: Floats = tree.value[pos]
    return out


def fit_gbm(x: Floats, y: Floats, params: GBMParams = GBMParams()) -> GBMModel:
    """Ajusta o boosting nas linhas de treino `x` (n × k, sem NaN) e alvo `y` em {0, 1}."""
    if x.ndim != 2 or len(x) != len(y) or len(y) == 0:
        raise ValueError("x (n × k) e y (n) incompatíveis ou vazios")
    if not np.isfinite(x).all():
        raise ValueError("x com valor ausente: o modelo não imputa")
    rate = float(np.clip(y.mean(), 1e-6, 1 - 1e-6))
    base = float(np.log(rate / (1.0 - rate)))
    edges = bin_edges(x, params.n_bins)
    b = digitize(x, edges)
    n_bins = int(b.max()) + 1
    score = np.full(len(y), base)
    trees: list[Tree] = []
    for _ in range(params.n_rounds):
        prob = _sigmoid(score)
        g = prob - y
        h = np.maximum(prob * (1.0 - prob), 1e-12)
        tree = _grow(b, g, h, n_bins, params)
        trees.append(tree)
        score = score + params.learning_rate * _tree_output(tree, b)
    return GBMModel(edges, base, tuple(trees), params)


def predict_gbm(model: GBMModel, x: Floats) -> Floats:
    """Probabilidade prevista, com as faixas congeladas do treino."""
    b = digitize(x, model.edges)
    score = np.full(len(x), model.base_score)
    for tree in model.trees:
        score = score + model.params.learning_rate * _tree_output(tree, b)
    return _sigmoid(score)
