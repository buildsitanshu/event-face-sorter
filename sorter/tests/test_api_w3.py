import io
import zipfile

from convo_gallery import config
from convo_gallery.api import app
from convo_gallery.db import open_db
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch, with_index=True):
    db = tmp_path / "g.db"
    web = tmp_path / "web"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(config, "WEB_DIR", str(web))
    if with_index:
        web.mkdir()
        (web / "index.html").write_text("<title>Viewer</title>")
    conn = open_db(str(db))
    conn.execute("INSERT INTO clusters (id, label, rep_face_id, face_count, media_count) VALUES (1, NULL, 1, 2, 2)")
    for mid, name in ((1, "a.jpg"), (2, "b.jpg")):
        src = tmp_path / name
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
    return TestClient(app)


def test_web_and_root(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/web/"
    r = c.get("/web/")
    assert r.status_code == 200 and "<title>Viewer</title>" in r.text
    assert c.get("/web/sub/../../etc/passwd").status_code == 404
    assert c.get("/web/%2e%2e/%2e%2e/etc/passwd").status_code == 404
    assert c.get("/web/missing.html").status_code == 404


def test_root_without_export(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, with_index=False)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 200 and "gallery not exported yet" in r.json()["message"]


def test_original_disposition(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/original/1").headers["content-disposition"].startswith("inline")
    assert c.get("/original/1?download=1").headers["content-disposition"].startswith("attachment")


def test_label(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/people/1/label", json={"label": "  Asha Rao  "})
    assert r.status_code == 200 and r.json()["name"] == "Asha Rao" and r.json()["label"] == "Asha Rao"
    conn = open_db(config.DB_PATH)
    assert conn.execute("SELECT label FROM clusters WHERE id=1").fetchone()[0] == "Asha Rao"
    conn.close()
    r = c.post("/api/people/1/label", json={"label": ""})
    assert r.status_code == 200 and r.json()["label"] is None and r.json()["name"] == "person-001"
    assert c.post("/api/people/999/label", json={"label": "x"}).status_code == 404


def test_zip(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/zip/1")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == ["a.jpg", "b.jpg"]
    assert c.get("/zip/999").status_code == 404


def test_local_urls(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    m = c.get("/api/people/1").json()["media"][0]
    assert m["download_url"].startswith("/original/")
    assert c.get("/api/download/manifest/1").json()["files"][0]["download_url"].startswith("/original/")
