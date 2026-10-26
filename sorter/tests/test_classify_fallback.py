import numpy as np

from convo_gallery.db import open_db
from convo_gallery.reference import classify_all

TAG = "antelopev2@cpu"


def _vec(axis, noise=None):
    v = np.zeros(512, dtype=np.float32)
    v[axis] = 1.0
    if noise is not None:
        v = v + noise
        v = v / np.linalg.norm(v)
    return v.astype(np.float32)


def test_unsupervised_then_roster():
    conn = open_db(":memory:")
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, kind, source, status) "
        "VALUES (1,'local-x','a.jpg','jpeg','local','processed')"
    )
    rng = np.random.default_rng(0)
    e1 = _vec(0)
    e2 = _vec(0, rng.normal(0, 0.01 / np.sqrt(512), 512).astype(np.float32))
    e3 = _vec(1)
    for fid, e in ((1, e1), (2, e2), (3, e3)):
        conn.execute(
            "INSERT INTO faces (id, media_id, source, bbox, det_score, face_px, embedding, "
            "embed_model_tag, is_usable) VALUES (?,?,?,?,?,?,?,?,1)",
            (fid, 1, "photo", "[0,0,1,1]", 0.9, 100, e.tobytes(), TAG),
        )
    conn.commit()
    result = classify_all(conn)
    assert result["mode"] == "unsupervised"
    assert conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0] == 2
    cid = {r[0]: r[1] for r in conn.execute("SELECT id, cluster_id FROM faces")}
    assert cid[1] == cid[2] and cid[3] != cid[1]

    conn.execute(
        "INSERT INTO reference_faces (drive_file_id, filename, embedding, ref_person_id, embed_model_tag) "
        "VALUES ('r1','Asha.jpg',?,1,?)",
        (e1.tobytes(), TAG),
    )
    conn.commit()
    assert classify_all(conn)["mode"] == "roster"
