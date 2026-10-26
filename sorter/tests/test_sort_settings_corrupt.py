import json

import pytest
from convo_gallery import cli, config
from convo_gallery.db import open_db
from test_sort_settings import _point_config, _seed


def _setup(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    _point_config(monkeypatch, data)
    conn = open_db(str(data / "gallery.db"))
    _seed(conn, tmp_path / "media")
    conn.close()
    return data


def test_corrupt_file_no_flags_exits_1(tmp_path, monkeypatch):
    data = _setup(tmp_path, monkeypatch)
    (data / "sort-settings.json").write_text("{not json")
    with pytest.raises(SystemExit) as e:
        cli.main(["sort"])
    assert e.value.code not in (0, None)
    assert "is unreadable" in str(e.value)


def test_corrupt_file_with_both_flags_runs_and_rewrites(tmp_path, monkeypatch, capsys):
    data = _setup(tmp_path, monkeypatch)
    (data / "sort-settings.json").write_text("{not json")
    cli.main(["sort", "--min-photos", "2", "--mode", "copy"])
    assert "(from flags)" in capsys.readouterr().out
    saved = json.loads((data / "sort-settings.json").read_text())
    assert saved["min_photos"] == 2 and saved["mode"] == "copy"


def test_wrong_type_no_flags_exits_1(tmp_path, monkeypatch):
    data = _setup(tmp_path, monkeypatch)
    (data / "sort-settings.json").write_text(json.dumps({"min_photos": "2"}))
    with pytest.raises(SystemExit) as e:
        cli.main(["sort"])
    assert e.value.code not in (0, None)
    assert "is unreadable" in str(e.value)
    assert config.DATA_DIR == str(data)
