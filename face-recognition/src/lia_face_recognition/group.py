# face.group: turn a bag of embeddings into people. Wraps Chinese Whispers and picks a
# representative (medoid: the face closest to its cluster centroid) per cluster for the UI grid.
from __future__ import annotations

import numpy as np

from .chinese_whispers import chinese_whispers
from .config import CLUSTER_THRESHOLD


def _representatives(X: np.ndarray, labels: list[int]) -> dict[int, int]:
    """For each cluster, the index of the medoid face (max mean-similarity to its peers)."""
    reps: dict[int, int] = {}
    labels_arr = np.asarray(labels)
    for lab in set(labels):
        idx = np.nonzero(labels_arr == lab)[0]
        if len(idx) == 1:
            reps[int(lab)] = int(idx[0])
            continue
        sub = X[idx]
        centroid = sub.mean(axis=0)
        centroid /= np.linalg.norm(centroid) + 1e-9
        sims = sub @ centroid
        reps[int(lab)] = int(idx[int(np.argmax(sims))])
    return reps


def group_faces(embeddings, *, threshold: float = CLUSTER_THRESHOLD, seed: int = 0) -> dict:
    """Cluster embeddings into people. Returns labels (one per input), the representative index
    per cluster, and the cluster count. Pure + deterministic for a fixed (embeddings, threshold, seed)."""
    X = np.asarray(embeddings, dtype=np.float32)
    labels = chinese_whispers(X, threshold=threshold, seed=seed)
    reps = _representatives(X, labels) if len(labels) else {}
    return {
        "labels": labels,
        "representatives": reps,
        "n_clusters": len(set(labels)),
        "threshold": threshold,
    }
