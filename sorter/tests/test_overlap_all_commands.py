import pytest
from convo_gallery import cli, config


@pytest.mark.parametrize("cmd", ["summary", "export-web", "classify"])
def test_every_command_refuses_overlap_before_writing(tmp_path, monkeypatch, cmd):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "one.jpg").write_bytes(b"x")
    data = photos / "data"
    monkeypatch.setattr(config, "MEDIA_DIR", str(photos))
    monkeypatch.setattr(config, "ROSTER_DIR", "")
    monkeypatch.setattr(config, "DATA_DIR", str(data))
    monkeypatch.setattr(config, "DB_PATH", str(data / "gallery.db"))
    for name in ("PREVIEWS_DIR", "CROPS_DIR", "FRAMES_DIR", "ORIGINALS_DIR"):
        monkeypatch.setattr(config, name, str(data / name.lower()))
    with pytest.raises(SystemExit) as e:
        cli.main([cmd])
    assert "is inside the photo folder" in str(e.value)
    assert not data.exists()
    assert sorted(p.name for p in photos.iterdir()) == ["one.jpg"]
