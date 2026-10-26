# The accuracy fix's correctness core: matching NEVER compares embeddings across model spaces.
# A buffalo_l candid face must be invisible to an antelopev2 roster (cosine distance across spaces
# is meaningless), and score_roster.invariant must flag any matched face that leaks across.
import numpy as np

from convo_gallery.db import open_db
from convo_gallery.reference import _roster_tag, match_and_rebuild
from convo_gallery.score_roster import invariant

DIM = 512
ANTE = "antelopev2@cpu"
BUFF = "buffalo_l@cpu"


def _unit(i: int) -> bytes:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v.tobytes()


def _ref(conn, rid, rp, blob, tag=ANTE):
    conn.execute(
        "INSERT INTO reference_faces (id, filename, embedding, ref_person_id, embed_model_tag) VALUES (?,?,?,?,?)",
        (rid, f"ref{rid}.jpg", blob, rp, tag),
    )


def _media(conn, mid, kind="jpeg", tag=ANTE):
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, kind, preview_path, status, detect_model_tag) "
        "VALUES (?,?,?,?,?, 'processed', ?)",
        (mid, f"f{mid}", f"f{mid}.jpg", kind, f"/p/{mid}.jpg", tag),
    )


def _face(conn, fid, mid, blob, tag):
    conn.execute(
        "INSERT INTO faces (id, media_id, bbox, det_score, face_px, embedding, embed_model_tag, is_usable) "
        "VALUES (?,?,?,?,?,?,?,1)",
        (fid, mid, "[0,0,50,50]", 0.9, 50, blob, tag),
    )


def _seed_roster(conn):
    _ref(conn, 1, 0, _unit(0))
    _ref(conn, 2, 1, _unit(1))


def test_matching_excludes_other_model_space():
    conn = open_db(":memory:")
    _seed_roster(conn)
    _media(conn, 10, tag=ANTE)
    _media(conn, 11, tag=BUFF)
    _face(conn, 100, 10, _unit(0), ANTE)  # identical to person 0, SAME space -> must match
    _face(conn, 101, 11, _unit(0), BUFF)  # identical vector but WRONG space -> must be ignored
    conn.commit()

    res = match_and_rebuild(conn, threshold=0.40)
    assert res["faces_total"] == 1, "only the antelopev2 candid is in the matching space"
    matched = conn.execute("SELECT id FROM faces WHERE cluster_id IS NOT NULL").fetchall()
    assert [r[0] for r in matched] == [100]
    assert conn.execute("SELECT cluster_id FROM faces WHERE id=101").fetchone()[0] is None


def test_invariant_flags_cross_space_contamination():
    conn = open_db(":memory:")
    _seed_roster(conn)
    _media(conn, 10, tag=ANTE)
    _face(conn, 100, 10, _unit(0), ANTE)
    conn.commit()
    match_and_rebuild(conn, threshold=0.40)
    assert invariant(conn)["ok"], "a clean unified space passes"

    # force a buffalo face into a cluster -> contamination the invariant must catch
    cl = conn.execute("SELECT id FROM clusters LIMIT 1").fetchone()[0]
    _media(conn, 11, tag=BUFF)
    _face(conn, 101, 11, _unit(0), BUFF)
    conn.execute("UPDATE faces SET cluster_id=? WHERE id=101", (cl,))
    conn.commit()
    out = invariant(conn)
    assert not out["ok"]
    assert any("outside the roster model space" in s for s in out["violations"])


def test_roster_tag_rejects_mixed_models():
    conn = open_db(":memory:")
    _ref(conn, 1, 0, _unit(0), tag=ANTE)
    _ref(conn, 2, 1, _unit(1), tag=BUFF)
    conn.commit()
    try:
        _roster_tag(conn)
        raised = False
    except ValueError:
        raised = True
    assert raised, "a roster that mixes models must raise, not silently corrupt matches"
