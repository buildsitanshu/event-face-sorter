import os
import tempfile

from convo_gallery import config
from convo_gallery.api import app
from convo_gallery.db import open_db
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "g.db"))
    conn = open_db(config.DB_PATH)
    conn.execute("INSERT INTO clusters (id, label, rep_face_id, face_count, media_count) VALUES (1, NULL, 1, 1, 1)")
    src = tmp_path / "a.jpg"
    src.write_bytes(b"a")
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, kind, status, source, local_path) "
        "VALUES (1,'local-1','a.jpg','jpeg','processed','local',?)",
        (str(src),),
    )
    conn.execute(
        "INSERT INTO faces (id, media_id, bbox, det_score, face_px, embedding, crop_path, cluster_id, is_usable) "
        "VALUES (1,1,'[1,1,5,5]',0.9,80,?, '/none.jpg',1,1)",
        (b"\0" * 2048,),
    )
    conn.commit()
    conn.close()
    return TestClient(app)


def test_label_is_capped_at_80(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/people/1/label", json={"label": "A" * 500})
    assert r.status_code == 200
    assert len(r.json()["name"]) <= 80
    conn = open_db(config.DB_PATH)
    stored = conn.execute("SELECT label FROM clusters WHERE id=1").fetchone()[0]
    conn.close()
    assert len(stored) == 80


def test_zip_success_leaves_no_temp_zip(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    r = c.get("/zip/1")
    assert r.status_code == 200 and r.content
    assert [f for f in os.listdir(scratch) if f.endswith(".zip")] == []
