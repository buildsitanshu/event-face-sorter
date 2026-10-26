# Clustering correctness + determinism. No model needed: synthetic 512-d embeddings in three
# tight, well-separated clusters. Proves face.group recovers the right people and is reproducible.
import numpy as np

from lia_face_recognition.group import group_faces


def _normed(v: np.ndarray) -> np.ndarray:
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)


def _make(seed: int = 0):
    rng = np.random.default_rng(seed)
    dim, per = 512, 8
    centers = [rng.normal(size=dim) for _ in range(3)]
    rows, truth = [], []
    for ci, c in enumerate(centers):
        for _ in range(per):
            rows.append(_normed(c + 0.02 * rng.normal(size=dim)))
            truth.append(ci)
    return np.asarray(rows, dtype=np.float32), truth


def test_recovers_three_people():
    X, truth = _make()
    out = group_faces(X, threshold=0.35, seed=0)
    assert out["n_clusters"] == 3
    # every ground-truth cluster maps to exactly one predicted label (no split, no merge)
    from collections import defaultdict

    groups: dict[int, set] = defaultdict(set)
    for lab, t in zip(out["labels"], truth):
        groups[t].add(lab)
    assert all(len(s) == 1 for s in groups.values())
    # representatives: one valid index per predicted cluster
    assert set(out["representatives"]) == set(out["labels"])


def test_deterministic():
    X, _ = _make()
    assert group_faces(X, seed=0)["labels"] == group_faces(X, seed=0)["labels"]


def test_empty_and_singleton():
    assert group_faces(np.zeros((0, 512), dtype=np.float32))["labels"] == []
    one = group_faces(_normed(np.random.default_rng(1).normal(size=512)).reshape(1, 512))
    assert one["labels"] == [0] and one["n_clusters"] == 1
