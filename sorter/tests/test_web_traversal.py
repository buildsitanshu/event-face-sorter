import os

import pytest
from convo_gallery import config
from convo_gallery.api import app, web
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def tree(tmp_path, monkeypatch):
    (tmp_path / "secret.txt").write_text("SECRET")
    (tmp_path / "web2").mkdir()
    (tmp_path / "web2" / "s.txt").write_text("SIBLING")
    (tmp_path / "web" / "sub").mkdir(parents=True)
    (tmp_path / "web" / "index.html").write_text("ROOT-INDEX")
    (tmp_path / "web" / "sub" / "index.html").write_text("SUB-INDEX")
    monkeypatch.setattr(config, "WEB_DIR", str(tmp_path / "web"))
    return tmp_path


@pytest.mark.parametrize(
    "raw",
    ["../secret.txt", "sub/../../secret.txt", "../web2/s.txt", "/etc/passwd", "%2e%2e/secret.txt", "missing.html"],
)
def test_escape_and_missing_paths_are_404(tree, raw):
    # called directly: the httpx TestClient normalises ".." before sending, so it cannot carry these
    with pytest.raises(HTTPException) as ei:
        web(raw)
    assert ei.value.status_code == 404


def test_nul_byte_is_404_not_500(tree):
    with pytest.raises(HTTPException) as ei:
        web("index.html\x00.png")
    assert ei.value.status_code == 404


def test_index_files_are_served(tree):
    assert web("").path == os.path.realpath(tree / "web" / "index.html")
    assert web("sub/").path == os.path.realpath(tree / "web" / "sub" / "index.html")
    c = TestClient(app)
    assert c.get("/web/").text == "ROOT-INDEX"
    assert c.get("/web/sub/").text == "SUB-INDEX"


def test_encoded_dotdot_over_http(tree):
    r = TestClient(app).get("/web/%2e%2e/secret.txt", follow_redirects=False)
    assert r.status_code == 404
    assert "SECRET" not in r.text
