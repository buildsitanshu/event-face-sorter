# Unit tests for the pipeline glue that needs no Drive/model: media classification, EXIF-time
# parsing, sessionization, and the static gallery export (renders pages + Drive download links).
import os

from convo_gallery.db import open_db
from convo_gallery.export import export_gallery
from convo_gallery.group_stage import _epoch, sessionize
from convo_gallery.ingest import classify
from convo_gallery.links import drive_download_url


def test_classify():
    assert classify("IMG_1.CR3", None) == "raw"
    assert classify("a.NEF", None) == "raw"
    assert classify("p.jpg", None) == "jpeg"
    assert classify("p.HEIC", None) == "jpeg"
    assert classify("clip.MP4", "video/mp4") == "video"
    assert classify("clip.mov", None) == "video"
    assert classify("notes.txt", None) == "other"


def test_epoch():
    assert _epoch("2026:06:23 14:30:00") == 1782225000
    assert _epoch(None) is None
    assert _epoch("garbage") is None


def test_large_file_gets_confirm_token():
    assert "confirm=t" in drive_download_url("X", 300 * 1024 * 1024)
    assert "confirm=t" not in drive_download_url("X", 5 * 1024 * 1024)


def _seed(conn):
    conn.execute("INSERT INTO clusters (id, rep_face_id, face_count, media_count, is_unknown, cluster_run_id) VALUES (7, 1, 2, 2, 0, 1)")
    for mid, name, dt in [(1, "a.cr3", "2026:06:23 10:00:00"), (2, "b.mp4", "2026:06:23 14:00:00")]:
        kind = "video" if name.endswith(".mp4") else "raw"
        conn.execute(
            "INSERT INTO media_items (id, drive_file_id, filename, size_bytes, kind, datetime_original, status) VALUES (?,?,?,?,?,?, 'processed')",
            (mid, f"file{mid}", name, 200_000_000 if kind == "video" else 26_000_000, kind, dt),
        )
    for fid, mid in [(1, 1), (2, 2)]:
        conn.execute(
            "INSERT INTO faces (id, media_id, source, bbox, det_score, face_px, embedding, crop_path, cluster_id, is_usable) "
            "VALUES (?,?,?,?,?,?,?,?,7,1)",
            (fid, mid, "photo", "[0,0,1,1]", 0.9, 100, bytes(2048), None),
        )
    conn.commit()


def test_sessionize_splits_on_gap():
    conn = open_db(":memory:")
    _seed(conn)
    res = sessionize(conn, gap=90 * 60)  # 4h apart -> 2 sessions
    assert res["sessions"] == 2 and res["timed_media"] == 2


def test_export_renders_pages_and_links(tmp_path):
    conn = open_db(":memory:")
    _seed(conn)
    out = str(tmp_path / "gallery")
    res = export_gallery(conn, out_dir=out)
    assert res["people"] == 1
    assert os.path.exists(os.path.join(out, "index.html"))
    assert os.path.exists(os.path.join(out, "person_7.html"))
    page = open(os.path.join(out, "person_7.html"), encoding="utf-8").read()
    assert "uc?export=download&id=file1" in page  # photo direct link
    assert "confirm=t" in page  # the 200 MB video link carries the confirm token
