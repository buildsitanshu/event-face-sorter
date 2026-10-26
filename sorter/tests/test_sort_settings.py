import json
import os

import pytest
from convo_gallery import cli, config
from convo_gallery.db import open_db
from convo_gallery.export_sorted import export_sorted
from PIL import Image


def _face(conn, media_id, cluster_id):
    conn.execute(
        "INSERT INTO faces (media_id, bbox, det_score, face_px, embedding, cluster_id, is_usable) "
        "VALUES (?, '[1,1,9,9]', 0.9, 80, ?, ?, 1)",
        (media_id, b"\0" * 2048, cluster_id),
    )


def _media(conn, mid, name, path):
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, size_bytes, kind, status, source, local_path) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (mid, f"local-{name}", name, None, "jpeg", "processed", "local", path),
    )


def _seed(conn, media):
    media.mkdir()
    for i, (n, col) in enumerate([("a", (255, 0, 0)), ("b", (0, 255, 0)), ("c", (0, 0, 255))], start=1):
        Image.new("RGB", (32, 32), col).save(media / f"{n}.jpg")
        _media(conn, i, f"{n}.jpg", str(media / f"{n}.jpg"))
    for cid, label, mc in [(1, "Asha Rao", 2), (2, None, 2), (3, None, 1)]:
        conn.execute("INSERT INTO clusters (id, label, face_count, media_count) VALUES (?,?,?,?)", (cid, label, mc, mc))
    for mid, cid in [(1, 1), (2, 1), (2, 2), (3, 2), (3, 3)]:
        _face(conn, mid, cid)
    conn.commit()


def _point_config(monkeypatch, data):
    monkeypatch.setattr(config, "DATA_DIR", str(data))
    monkeypatch.setattr(config, "DB_PATH", str(data / "gallery.db"))
    monkeypatch.setattr(config, "SORTED_DIR", str(data / "sorted"))
    for name in ("PREVIEWS_DIR", "CROPS_DIR", "FRAMES_DIR", "ORIGINALS_DIR"):
        monkeypatch.setattr(config, name, str(data / name.lower()))


def _folders(data):
    return sorted(p.name for p in (data / "sorted").iterdir() if p.is_dir())


def test_export_sorted_writes_settings(tmp_path):
    conn = open_db(":memory:")
    _seed(conn, tmp_path / "media")
    out = tmp_path / "sorted"
    export_sorted(conn, str(out), min_photos=3, mode="hardlink")
    saved = json.loads((tmp_path / "sort-settings.json").read_text())
    assert saved["min_photos"] == 3 and saved["mode"] == "hardlink" and isinstance(saved["written_at"], int)


def test_sort_reuses_then_overrides(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    data.mkdir()
    _point_config(monkeypatch, data)
    conn = open_db(str(data / "gallery.db"))
    _seed(conn, tmp_path / "media")
    export_sorted(conn, str(data / "sorted"), min_photos=2, mode="hardlink")
    conn.close()
    assert _folders(data) == ["Asha Rao", "person-002"]

    cli.main(["sort"])
    out = capsys.readouterr().out
    assert "sort settings: min_photos=2 mode=hardlink (from sort-settings.json)" in out
    assert _folders(data) == ["Asha Rao", "person-002"]
    assert os.stat(data / "sorted" / "Asha Rao" / "a.jpg").st_nlink >= 2  # hardlink mode was reused

    cli.main(["sort", "--min-photos", "1"])
    out = capsys.readouterr().out
    assert "sort settings: min_photos=1 mode=hardlink (from flags)" in out
    assert _folders(data) == ["Asha Rao", "person-002", "person-003"]
    assert json.loads((data / "sort-settings.json").read_text())["min_photos"] == 1


def test_sort_without_stored_settings_uses_defaults(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    data.mkdir()
    _point_config(monkeypatch, data)
    conn = open_db(str(data / "gallery.db"))
    _seed(conn, tmp_path / "media")
    conn.close()
    cli.main(["sort"])
    assert f"sort settings: min_photos={config.MIN_PHOTOS} mode={config.SORT_MODE} (from defaults)" in capsys.readouterr().out


def test_sort_with_no_run_refuses_and_creates_nothing(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    data.mkdir()
    _point_config(monkeypatch, data)
    with pytest.raises(SystemExit) as e:
        cli.main(["sort"])
    assert e.value.code == 1
    assert f"no run found in {data}: run ./run.sh --photos <folder> first" in capsys.readouterr().out
    assert os.listdir(data) == []


def test_sort_with_missing_data_dir_creates_nothing(tmp_path, monkeypatch):
    data = tmp_path / "never"
    _point_config(monkeypatch, data)
    with pytest.raises(SystemExit) as e:
        cli.main(["sort"])
    assert e.value.code == 1
    assert not data.exists()
