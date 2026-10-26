import json
import os

import pytest
from convo_gallery.db import open_db
from convo_gallery.export_sorted import MARKER, export_sorted, folder_name
from PIL import Image


def _face(conn, media_id, cluster_id):
    conn.execute(
        "INSERT INTO faces (media_id, bbox, det_score, face_px, embedding, cluster_id, is_usable) "
        "VALUES (?, '[1,1,9,9]', 0.9, 80, ?, ?, 1)",
        (media_id, b"\0" * 2048, cluster_id),
    )


def _media(conn, mid, name, path, source="local", drive_id=None, size=None):
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, size_bytes, kind, status, source, local_path) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (mid, drive_id or f"local-{name}", name, size, "jpeg", "processed", source, path),
    )


def _setup(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    conn = open_db(":memory:")
    for i, (n, col) in enumerate([("a", (255, 0, 0)), ("b", (0, 255, 0)), ("c", (0, 0, 255))], start=1):
        Image.new("RGB", (32, 32), col).save(media / f"{n}.jpg")
        _media(conn, i, f"{n}.jpg", str(media / f"{n}.jpg"))
    for cid, label, mc in [(1, "Asha Rao", 2), (2, None, 2), (3, None, 1)]:
        conn.execute("INSERT INTO clusters (id, label, face_count, media_count) VALUES (?,?,?,?)", (cid, label, mc, mc))
    for mid, cid in [(1, 1), (2, 1), (2, 2), (3, 2), (3, 3)]:
        _face(conn, mid, cid)
    conn.commit()
    return conn, media


def test_folder_name():
    assert folder_name("A/B: C?", 9) == "AB C"
    assert folder_name(None, 9) == "person-009"
    assert folder_name("???", 4) == "person-004"


def test_export_sorted_copy_and_rerun(tmp_path):
    conn, media = _setup(tmp_path)
    out = tmp_path / "sorted"
    res = export_sorted(conn, str(out), min_photos=2)
    assert res["people"] == 2 and res["files_written"] == 4 and res["singles"] == 1
    assert {p.name for p in out.iterdir() if p.is_dir()} == {"Asha Rao", "person-002"}
    assert sorted(os.listdir(out / "Asha Rao")) == ["a.jpg", "b.jpg"]
    assert sorted(os.listdir(out / "person-002")) == ["b.jpg", "c.jpg"]
    for n in ("a.jpg", "b.jpg"):
        assert (out / "Asha Rao" / n).read_bytes() == (media / n).read_bytes()
    idx = json.loads((out / "index.json").read_text())
    assert len(idx["people"]) == 2 and idx["singles"][0]["cluster_id"] == 3
    assert (out / MARKER).exists() and (out / "README.txt").exists()
    again = export_sorted(conn, str(out), min_photos=2)
    assert again == res
    assert {p.name for p in out.iterdir() if p.is_dir()} == {"Asha Rao", "person-002"}


def test_refuses_unmarked_and_source_dirs(tmp_path):
    conn, media = _setup(tmp_path)
    existing = tmp_path / "precious"
    existing.mkdir()
    (existing / "x.txt").write_text("keep")
    with pytest.raises(ValueError):
        export_sorted(conn, str(existing))
    assert (existing / "x.txt").exists()
    with pytest.raises(ValueError):
        export_sorted(conn, str(media / "sorted"))
    with pytest.raises(ValueError):
        export_sorted(conn, str(tmp_path))


def test_hardlink_mode(tmp_path):
    conn, media = _setup(tmp_path)
    out = tmp_path / "sorted"
    export_sorted(conn, str(out), min_photos=2, mode="hardlink")
    assert os.stat(out / "Asha Rao" / "a.jpg").st_ino == os.stat(media / "a.jpg").st_ino
    with pytest.raises(ValueError):
        export_sorted(conn, str(out), mode="bogus")


def test_drive_item_writes_links_not_files(tmp_path):
    conn, _ = _setup(tmp_path)
    _media(conn, 4, "d.jpg", None, source="drive", drive_id="XYZ", size=5)
    _face(conn, 4, 1)
    conn.execute("UPDATE clusters SET media_count=3 WHERE id=1")
    conn.commit()
    out = tmp_path / "sorted"
    res = export_sorted(conn, str(out), min_photos=2)
    assert res["links_written"] == 1
    assert "XYZ" in (out / "Asha Rao" / "drive-links.txt").read_text()
    assert not (out / "Asha Rao" / "d.jpg").exists()
