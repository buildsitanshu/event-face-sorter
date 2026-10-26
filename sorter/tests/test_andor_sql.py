# The correctness core: people-selection -> media items, for union (any) and intersection (all).
# Includes the duplicate-face trap (two faces of ONE person in one photo must not fake a
# two-person match) and the empty-selection-is-not-everything rule.
from convo_gallery.db import open_db
from convo_gallery.query.people import query_media_ids

A, B, C = 10, 11, 12  # cluster (person) ids


def _conn():
    conn = open_db(":memory:")
    cur = conn.cursor()
    for cid in (A, B, C):  # people must exist before faces reference them (FK)
        cur.execute("INSERT INTO clusters (id) VALUES (?)", (cid,))
    for mid in (1, 2, 3):
        cur.execute(
            "INSERT INTO media_items (id, drive_file_id, filename) VALUES (?,?,?)",
            (mid, f"file{mid}", f"f{mid}.cr3"),
        )
    # media 1: {A,B} · media 2: {A,A,C} (A twice) · media 3: {B}
    rows = [(1, A), (1, B), (2, A), (2, A), (2, C), (3, B)]
    for media_id, cl in rows:
        cur.execute(
            "INSERT INTO faces (media_id, bbox, det_score, face_px, embedding, cluster_id, is_usable) "
            "VALUES (?,?,?,?,?,?,1)",
            (media_id, "[0,0,1,1]", 0.9, 100, bytes(2048), cl),
        )
    conn.commit()
    return conn


def test_union_any():
    assert query_media_ids(_conn(), [A, B], mode="any") == [1, 2, 3]


def test_intersection_all_AB():
    assert query_media_ids(_conn(), [A, B], mode="all") == [1]


def test_intersection_all_AC_defeats_duplicate_trap():
    # media 2 has A twice + C; COUNT(DISTINCT cluster_id) over {A,C} = 2 -> match.
    # media 1 has A + B (no C) -> excluded.
    assert query_media_ids(_conn(), [A, C], mode="all") == [2]


def test_empty_selection_is_not_everything():
    c = _conn()
    assert query_media_ids(c, [], mode="any") == []
    assert query_media_ids(c, [], mode="all") == []


def test_duplicate_selection_dedupes():
    # passing A twice == passing A once (k=1): every item containing A
    assert query_media_ids(_conn(), [A, A], mode="all") == [1, 2]


def test_unusable_faces_excluded():
    c = _conn()
    c.execute("INSERT INTO media_items (id, drive_file_id, filename) VALUES (4,'file4','f4.cr3')")
    c.execute(
        "INSERT INTO faces (media_id,bbox,det_score,face_px,embedding,cluster_id,is_usable) "
        "VALUES (4,'[0,0,1,1]',0.9,100,?,?,0)",
        (bytes(2048), A),
    )
    c.commit()
    assert 4 not in query_media_ids(c, [A], mode="any")
