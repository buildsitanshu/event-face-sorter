# End-to-end proof on InsightFace's bundled multi-face sample. Downloads the buffalo_l model on
# first run, so it's separated from the fast unit tests. Validates real detection + 512-d
# L2-normalized embeddings + that grouping separates the distinct people in the image.
import numpy as np
import pytest

from lia_face_recognition.embed import detect_and_embed
from lia_face_recognition.group import group_faces


def test_detect_on_bundled_sample():
    pytest.importorskip("insightface")
    from insightface.data import get_image

    img = get_image("t1")  # bundled BGR ndarray with several faces
    faces = detect_and_embed(img)
    assert len(faces) >= 2
    for f in faces:
        assert len(f.embedding) == 512
        assert abs(float(np.linalg.norm(np.asarray(f.embedding))) - 1.0) < 1e-2

    usable = [f for f in faces if f.is_usable]
    assert len(usable) >= 2
    groups = group_faces([f.embedding for f in usable])
    assert groups["n_clusters"] >= 2
