import sqlite3

import pytest
from convo_gallery import cli
from convo_gallery.db import open_db

ODD_DIRS = ["odd#dir", "odd?dir", "odd%41dir", "with space"]


def _seeded(path):
    conn = open_db(str(path))
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, size_bytes, kind, status, source, local_path) "
        "VALUES (1,'local-a','a.jpg',NULL,'jpeg','processed','local','/x/a.jpg')"
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("name", ODD_DIRS)
def test_has_run_true_in_oddly_named_dir(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    db = d / "gallery.db"
    _seeded(db)
    before = sorted(p.name for p in tmp_path.rglob("*") if "-wal" not in p.name and "-shm" not in p.name)
    assert cli._has_run(str(db)) is True
    after = sorted(p.name for p in tmp_path.rglob("*") if "-wal" not in p.name and "-shm" not in p.name)
    assert before == after
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]  # nothing stray in the parent


def test_has_run_false_for_empty_migrated_db(tmp_path):
    db = tmp_path / "gallery.db"
    open_db(str(db)).close()
    assert cli._has_run(str(db)) is False


def test_has_run_false_for_missing_file_and_creates_nothing(tmp_path):
    assert cli._has_run(str(tmp_path / "nope.db")) is False
    assert list(tmp_path.iterdir()) == []


def test_has_run_open_error_exits_1(tmp_path, monkeypatch, capsys):
    db = tmp_path / "gallery.db"
    _seeded(db)

    def boom(*a, **k):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", boom)
    with pytest.raises(SystemExit) as e:
        cli._has_run(str(db))
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert f"could not open {db}: unable to open database file" in out
