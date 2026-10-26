from convo_gallery import config
from convo_gallery.api import app
from convo_gallery.db import open_db
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    db = tmp_path / "g.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(config, "WEB_DIR", str(tmp_path / "web"))
    src = tmp_path / "pic.jpg"
    src.write_bytes(b"known-bytes-123")
    conn = open_db(str(db))
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, kind, status, source, local_path) "
        "VALUES (1, 'local-pic', 'pic.jpg', 'jpeg', 'processed', 'local', ?)",
        (str(src),),
    )
    conn.commit()
    conn.close()
    return TestClient(app)


def test_api_surface(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/people")
    assert r.status_code == 200 and "people" in r.json()
    r = client.get("/original/1")
    assert r.status_code == 200 and r.content == b"known-bytes-123"
    assert client.get("/original/999").status_code == 404
    assert client.get("/login").status_code == 404
    r = client.get("/")
    assert r.status_code == 200 and "gallery not exported yet" in r.json()["message"]
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>Sorted</title>")
    r = client.get("/")
    assert r.status_code == 200 and "<title>Sorted</title>" in r.text
    # the /web static mount was created with check_dir=False but resolves its directory at import,
    # so it points at the real data/web, not this test's tmp dir: only the "/" route is asserted.
