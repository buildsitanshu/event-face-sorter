import pytest
from convo_gallery import cli, config


class Reached(Exception):
    """Raised by a patched first pipeline call to prove the overlap check let the run through."""


def _point_config(monkeypatch, data):
    monkeypatch.setattr(config, "DATA_DIR", str(data))
    monkeypatch.setattr(config, "DB_PATH", str(data / "gallery.db"))
    for name in ("PREVIEWS_DIR", "CROPS_DIR", "FRAMES_DIR", "ORIGINALS_DIR"):
        monkeypatch.setattr(config, name, str(data / name.lower()))


def test_data_inside_photos_refuses_before_any_write(tmp_path, monkeypatch, capsys):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "one.jpg").write_bytes(b"x")
    _point_config(monkeypatch, photos / "data")
    with pytest.raises(SystemExit) as e:
        cli.main(["run-all", "--photos", str(photos), "--skip-video"])
    assert e.value.code not in (0, None)
    assert "is inside the photo folder" in str(e.value)
    assert "CONVO_DATA_DIR=$HOME/event-face-sorter-data" in str(e.value)
    assert not (photos / "data").exists()
    assert sorted(p.name for p in photos.iterdir()) == ["one.jpg"]


def test_photos_inside_data_refuses_before_any_write(tmp_path, monkeypatch):
    data = tmp_path / "data"
    photos = data / "photos"
    photos.mkdir(parents=True)
    _point_config(monkeypatch, data)
    with pytest.raises(SystemExit) as e:
        cli.main(["run-all", "--photos", str(photos), "--skip-video"])
    assert "is inside the photo folder" in str(e.value)
    assert sorted(p.name for p in data.iterdir()) == ["photos"]


def test_headshots_inside_data_refuses(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    photos.mkdir()
    data = tmp_path / "data"
    people = data / "people"
    people.mkdir(parents=True)
    _point_config(monkeypatch, data)
    with pytest.raises(SystemExit):
        cli.main(["run-all", "--photos", str(photos), "--people", str(people), "--skip-video"])
    assert sorted(p.name for p in data.iterdir()) == ["people"]


def test_symlinked_data_dir_is_caught(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    photos.mkdir()
    link = tmp_path / "link"
    link.symlink_to(photos, target_is_directory=True)
    _point_config(monkeypatch, link / "data")
    with pytest.raises(SystemExit):
        cli.main(["run-all", "--photos", str(photos), "--skip-video"])
    assert not (photos / "data").exists()


def test_non_overlapping_pair_passes_the_check(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    photos.mkdir()
    _point_config(monkeypatch, tmp_path / "data")
    import convo_gallery.local_source as local_source

    def boom(*a, **k):
        raise Reached

    monkeypatch.setattr(local_source, "ingest_local", boom)
    with pytest.raises(Reached):
        cli.main(["run-all", "--photos", str(photos), "--skip-video"])
