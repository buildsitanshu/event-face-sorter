# reclaim_unfinished: rows a previous run claimed but never finished go back to the queue.
import pytest

from convo_gallery import pipeline
from convo_gallery.db import open_db
from convo_gallery.pipeline import reclaim_unfinished


def _insert(conn, mid, kind, status, claimed_by=None):
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, kind, status, claimed_by) VALUES (?,?,?,?,?,?)",
        (mid, f"file{mid}", f"f{mid}.jpg", kind, status, claimed_by),
    )


def _row(conn, mid):
    return conn.execute("SELECT status, claimed_by FROM media_items WHERE id=?", (mid,)).fetchone()


def test_reclaim_unfinished_returns_only_claimed_rows_of_the_given_kinds():
    conn = open_db(":memory:")
    _insert(conn, 1, "image", "listed")
    _insert(conn, 2, "image", "claimed", "local")
    _insert(conn, 3, "image", "processed", "local")
    _insert(conn, 4, "video", "claimed", "local")
    _insert(conn, 5, "image", "process_error", "local")
    conn.commit()

    assert reclaim_unfinished(conn, ("image",)) == 1

    assert tuple(_row(conn, 2)) == ("listed", None)
    assert tuple(_row(conn, 1)) == ("listed", None)
    assert tuple(_row(conn, 3)) == ("processed", "local")
    assert tuple(_row(conn, 4)) == ("claimed", "local")
    assert tuple(_row(conn, 5)) == ("process_error", "local")


class _Stop(Exception):
    pass


def test_run_reclaims_before_selecting(monkeypatch):
    conn = open_db(":memory:")
    calls = []

    def spy(c, kinds):
        calls.append((c, kinds))
        raise _Stop

    monkeypatch.setattr(pipeline, "reclaim_unfinished", spy)
    with pytest.raises(_Stop):
        pipeline.run(conn, ("jpeg",), workers=1)
    assert calls == [(conn, ("jpeg",))]
