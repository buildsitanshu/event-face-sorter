import os

import pytest
from convo_gallery import cli, config
from convo_gallery.db import open_db
from convo_gallery.local_source import enroll_local


def test_enroll_local_missing_dir(tmp_path):
    conn = open_db(":memory:")
    with pytest.raises(FileNotFoundError):
        enroll_local(conn, str(tmp_path / "nope"))


def test_enroll_local_path_is_a_file(tmp_path):
    f = tmp_path / "file.jpg"
    f.write_bytes(b"x")
    conn = open_db(":memory:")
    with pytest.raises(FileNotFoundError):
        enroll_local(conn, str(f))


def test_require_roster_dir_missing_and_present(tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.require_roster_dir({"mode": "local", "media": str(tmp_path), "roster": str(tmp_path / "nope")})
    assert "headshots folder not found" in str(e.value)
    cli.require_roster_dir({"mode": "local", "media": str(tmp_path), "roster": str(tmp_path)})
    cli.require_roster_dir({"mode": "local", "media": str(tmp_path), "roster": None})
    cli.require_roster_dir({"mode": "drive", "media": "mid", "roster": "driveFolderId"})


def test_run_all_fails_before_any_work_on_missing_roster(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    photos.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", str(data))
    monkeypatch.setattr(config, "DB_PATH", str(data / "gallery.db"))
    for name in ("PREVIEWS_DIR", "CROPS_DIR", "FRAMES_DIR", "ORIGINALS_DIR"):
        monkeypatch.setattr(config, name, str(data / name.lower()))
    with pytest.raises(SystemExit) as e:
        cli.main(["run-all", "--photos", str(photos), "--people", str(tmp_path / "nope")])
    assert "headshots folder not found" in str(e.value)
    assert not os.path.exists(data / "sorted")  # nothing was exported


def test_enroll_local_stores_name_without_extension(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import lia_face_recognition.embed as embed
    from PIL import Image

    monkeypatch.setattr(config, "PREVIEWS_DIR", str(tmp_path / "previews"))
    monkeypatch.setattr(config, "ensure_dirs", lambda: os.makedirs(config.PREVIEWS_DIR, exist_ok=True))
    monkeypatch.setattr(
        embed, "detect_and_embed",
        lambda _p: [SimpleNamespace(is_usable=True, face_px=90, embedding=[0.0] * 512)],
    )
    heads = tmp_path / "heads"
    heads.mkdir()
    Image.new("RGB", (40, 40)).save(heads / "Asha Rao.jpg")
    conn = open_db(":memory:")
    assert enroll_local(conn, str(heads))["enrolled"] == 1
    assert conn.execute("SELECT filename FROM reference_faces").fetchone()[0] == "Asha Rao"
