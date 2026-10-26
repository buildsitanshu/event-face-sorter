import os

import pytest
from PIL import Image

from convo_gallery.db import open_db
from convo_gallery.group_stage import _epoch
from convo_gallery.local_source import ingest_local, local_key, make_preview

DT = "2026:10:18 19:30:00"


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_migration_adds_local_columns():
    conn = open_db(":memory:")
    assert {"source", "local_path"} <= _cols(conn, "media_items")
    assert "local_path" in _cols(conn, "reference_faces")


def _tree(tmp_path):
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = DT
    Image.new("RGB", (64, 48), (200, 10, 10)).save(tmp_path / "a.jpg", exif=exif)
    (tmp_path / "sub").mkdir()
    Image.new("RGB", (32, 32)).save(tmp_path / "sub" / "b.png")
    (tmp_path / "c.txt").write_text("hi")
    (tmp_path / ".hidden.jpg").write_bytes(b"x")
    (tmp_path / "._d.jpg").write_bytes(b"x")
    (tmp_path / "x.cr3").write_bytes(b"")


def test_ingest_local_rows_and_idempotence(tmp_path):
    _tree(tmp_path)
    conn = open_db(":memory:")
    res = ingest_local(conn, str(tmp_path))
    assert res["total"] == 4 and res["new"] == 4
    rows = {
        r["drive_path"]: r
        for r in (
            dict(zip(
                ["drive_path", "kind", "status", "error_msg", "drive_file_id", "source",
                 "local_path", "datetime_original", "dt_utc"], row, strict=True))
            for row in conn.execute(
                "SELECT drive_path, kind, status, error_msg, drive_file_id, source, local_path, "
                "datetime_original, dt_utc FROM media_items"
            ).fetchall()
        )
    }
    assert set(rows) == {"a.jpg", "sub/b.png", "c.txt", "x.cr3"}
    for p in ("a.jpg", "sub/b.png"):
        assert rows[p]["status"] == "listed" and rows[p]["kind"] == "jpeg"
    assert rows["c.txt"]["status"] == "skipped" and rows["c.txt"]["error_msg"] == "not_media"
    assert rows["x.cr3"]["status"] == "skipped" and rows["x.cr3"]["error_msg"] == "local_raw_unsupported"
    a = rows["a.jpg"]
    assert a["drive_file_id"] == local_key("a.jpg") and a["drive_file_id"].startswith("local-")
    assert a["datetime_original"] == DT and a["dt_utc"] == _epoch(DT)
    assert a["source"] == "local"
    assert os.path.isabs(a["local_path"]) and os.path.exists(a["local_path"])
    again = ingest_local(conn, str(tmp_path))
    assert again["new"] == 0
    assert conn.execute("SELECT COUNT(*) FROM media_items").fetchone()[0] == 4


def test_make_preview(tmp_path):
    src = tmp_path / "big.png"
    Image.new("RGB", (3000, 2000), (1, 2, 3)).save(src)
    dst = tmp_path / "out.jpg"
    assert make_preview(str(src), str(dst)) is True
    with Image.open(dst) as im:
        assert im.format == "JPEG" and max(im.size) == 2048
    txt = tmp_path / "c.txt"
    txt.write_text("nope")
    bad = tmp_path / "bad.jpg"
    assert make_preview(str(txt), str(bad)) is False
    assert not bad.exists() and not (tmp_path / "bad.jpg.tmp").exists()


def test_ingest_missing_dir(tmp_path):
    conn = open_db(":memory:")
    with pytest.raises(FileNotFoundError):
        ingest_local(conn, str(tmp_path / "nope"))
