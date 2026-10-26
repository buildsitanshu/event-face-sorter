import io
import os
import tempfile
import zipfile

import pytest
from convo_gallery import config
from convo_gallery.api import app
from convo_gallery.db import open_db
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch, present, missing):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "g.db"))
    conn = open_db(config.DB_PATH)
    conn.execute("INSERT INTO clusters (id, label, rep_face_id, face_count, media_count) VALUES (1, NULL, 1, 2, 2)")
    mid = 0
    for name, exists in [(n, True) for n in present] + [(n, False) for n in missing]:
        mid += 1
        src = tmp_path / "orig" / name
        if exists:
            src.parent.mkdir(exist_ok=True)
            src.write_bytes(b"bytes-" + name.encode())
        conn.execute(
            "INSERT INTO media_items (id, drive_file_id, filename, kind, status, source, local_path) "
            "VALUES (?,?,?,'jpeg','processed','local',?)",
            (mid, f"local-{mid}", name, str(src)),
        )
        conn.execute(
            "INSERT INTO faces (id, media_id, bbox, det_score, face_px, embedding, crop_path, cluster_id, is_usable) "
            "VALUES (?,?,?,?,?,?,?,1,1)",
            (mid, mid, "[1,1,5,5]", 0.9, 80, b"\0" * 2048, "/none.jpg"),
        )
    conn.commit()
    conn.close()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return TestClient(app), scratch


def test_missing_original_is_reported(tmp_path, monkeypatch):
    c, scratch = _client(tmp_path, monkeypatch, ["a.jpg"], ["gone.jpg"])
    r = c.get("/zip/1")
    assert r.status_code == 200
    assert r.headers["X-Missing-Count"] == "1"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(zf.namelist()) == ["a.jpg", "missing.txt"]
    lines = zf.read("missing.txt").decode().splitlines()
    assert lines == ["These originals were not found on disk:", "gone.jpg"]
    assert [f for f in os.listdir(scratch) if f.endswith(".zip")] == []


def test_all_missing_is_404(tmp_path, monkeypatch):
    c, scratch = _client(tmp_path, monkeypatch, [], ["gone.jpg"])
    r = c.get("/zip/1")
    assert r.status_code == 404
    assert r.json()["detail"] == "no originals found on disk for this person"
    assert os.listdir(scratch) == []


def test_zip_failure_leaves_no_temp_file(tmp_path, monkeypatch):
    c, scratch = _client(tmp_path, monkeypatch, ["a.jpg"], [])

    def boom(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "write", boom)
    with pytest.raises(OSError):
        TestClient(app, raise_server_exceptions=True).get("/zip/1")
    assert os.listdir(scratch) == []
