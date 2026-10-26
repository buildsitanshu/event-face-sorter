# Chinese Whispers clustering on L2-normalized embeddings (cosine). Deterministic: a seeded
# RNG drives node order and a fixed tie-break (highest weight, then smallest label id), so the
# documented small-graph oscillation can't make runs disagree. Edges are built in row-blocks so
# memory stays O(block * n), not O(n^2), safe for tens of thousands of faces.
from __future__ import annotations

import random

import numpy as np

_BLOCK = 512


def _build_neighbors(X: np.ndarray, sim_threshold: float) -> list[list[tuple[int, float]]]:
    n = X.shape[0]
    neighbors: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for start in range(0, n, _BLOCK):
        end = min(start + _BLOCK, n)
        sims = X[start:end] @ X.T  # (block, n)
        for bi in range(end - start):
            i = start + bi
            row = sims[bi]
            # only j > i to avoid double-adding; an edge is symmetric
            js = np.nonzero(row[i + 1 :] > sim_threshold)[0] + (i + 1)
            for j in js.tolist():
                w = float(row[j])
                neighbors[i].append((j, w))
                neighbors[j].append((i, w))
    return neighbors


def _compact(labels: list[int]) -> list[int]:
    remap: dict[int, int] = {}
    out = []
    for lab in labels:
        if lab not in remap:
            remap[lab] = len(remap)
        out.append(remap[lab])
    return out


def chinese_whispers(
    embeddings, *, threshold: float = 0.35, iterations: int = 30, seed: int = 0
) -> list[int]:
    """Cluster embeddings into people. `threshold` is cosine DISTANCE (<= => same person).
    Returns a compact label per input row. Isolated nodes (no edge) each get their own label."""
    X = np.asarray(embeddings, dtype=np.float32)
    n = X.shape[0]
    if n == 0:
        return []
    if n == 1:
        return [0]
    sim_threshold = 1.0 - threshold  # cosine sim above this <=> distance below threshold
    neighbors = _build_neighbors(X, sim_threshold)

    labels = list(range(n))
    rng = random.Random(seed)
    order = list(range(n))
    for _ in range(iterations):
        rng.shuffle(order)
        changed = False
        for i in order:
            if not neighbors[i]:
                continue
            weight_by_label: dict[int, float] = {}
            for j, w in neighbors[i]:
                weight_by_label[labels[j]] = weight_by_label.get(labels[j], 0.0) + w
            # deterministic argmax: max weight, tie-break on smallest label id
            best = max(weight_by_label.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if labels[i] != best:
                labels[i] = best
                changed = True
        if not changed:
            break
    return _compact(labels)
