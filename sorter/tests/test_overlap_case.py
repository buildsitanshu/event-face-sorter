import os

import pytest
from convo_gallery.cli import refuse_overlap


def _inp(photos):
    return {"mode": "local", "media": str(photos), "roster": None}


def test_case_different_spelling_is_refused(tmp_path):
    photos = tmp_path / "CaseP"
    photos.mkdir()
    if os.path.exists(tmp_path / "casep"):  # case-insensitive filesystem
        with pytest.raises(SystemExit) as e:
            refuse_overlap(_inp(photos), str(tmp_path / "casep" / "data"))
        assert "is inside the photo folder" in str(e.value)
    else:
        # Documented no-op: on a case-sensitive filesystem "casep" is a different folder, so there is
        # nothing to refuse. The symlink test below still exercises the inode comparison.
        refuse_overlap(_inp(photos), str(tmp_path / "casep" / "data"))


def test_symlinked_spelling_is_refused_by_inode(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(photos)
    with pytest.raises(SystemExit):
        refuse_overlap(_inp(photos), str(link / "data"))


def test_reverse_direction_by_inode(tmp_path):
    data = tmp_path / "data"
    photos = data / "photos"
    photos.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(data)
    with pytest.raises(SystemExit):
        refuse_overlap(_inp(alias / "photos"), str(data))


def test_unrelated_folders_pass(tmp_path):
    (tmp_path / "photos").mkdir()
    (tmp_path / "out").mkdir()
    refuse_overlap(_inp(tmp_path / "photos"), str(tmp_path / "out" / "data"))
