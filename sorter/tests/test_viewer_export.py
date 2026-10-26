import os

from convo_gallery.db import open_db
from convo_gallery.export_web import export


def test_viewer_files_exported(tmp_path):
    conn = open_db(":memory:")
    res = export(conn, out_dir=str(tmp_path))
    assert res["viewer"] is True
    for name in ("index.html", "tokens.css", "app.js"):
        assert os.path.exists(tmp_path / name)
    html = (tmp_path / "index.html").read_text()
    assert 'href="tokens.css"' in html and 'src="app.js"' in html
    assert "http://" not in html and "https://" not in html
    js = (tmp_path / "app.js").read_text()
    assert "transition" not in js and "animation" not in js
    css = (tmp_path / "tokens.css").read_text()
    assert "--color-bg:" in css and "--fs-xs:" in css
