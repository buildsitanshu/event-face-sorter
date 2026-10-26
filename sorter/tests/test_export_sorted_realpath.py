import os

import pytest
from convo_gallery.db import open_db
from convo_gallery.export_sorted import MARKER, export_sorted
from PIL import Image


def _conn_with_photo(photos):
    photos.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16)).save(photos / "a.jpg")
    conn = open_db(":memory:")
    conn.execute(
        "INSERT INTO media_items (id, drive_file_id, filename, kind, status, source, local_path) "
        "VALUES (1,'local-a','a.jpg','jpeg','processed','local',?)",
        (str(photos / "a.jpg"),),
    )
    conn.commit()
    return conn


def test_symlink_to_photos_as_out_parent(tmp_path):
    photos = tmp_path / "photos"
    conn = _conn_with_photo(photos)
    link = tmp_path / "link"
    os.symlink(photos, link)
    with pytest.raises(ValueError):
        export_sorted(conn, str(link / "sorted"))
    assert sorted(os.listdir(photos)) == ["a.jpg"]


def test_alternate_spelling_through_symlinked_parent(tmp_path):
    real = tmp_path / "real"
    photos = real / "photos"
    conn = _conn_with_photo(photos)
    alias = tmp_path / "alias"
    os.symlink(real, alias)
    # the DB records the real path; the user spells the output through the alias
    with pytest.raises(ValueError):
        export_sorted(conn, str(alias / "photos" / "out"))
    assert sorted(os.listdir(photos)) == ["a.jpg"]


def test_headshot_dir_as_out_dir(tmp_path):
    conn = _conn_with_photo(tmp_path / "photos")
    heads = tmp_path / "heads"
    heads.mkdir()
    (heads / "Asha.jpg").write_bytes(b"x")
    conn.execute(
        "INSERT INTO reference_faces (drive_file_id, filename, embedding, embed_model_tag, local_path) "
        "VALUES ('local-h','Asha',?,'t',?)",
        (b"\0" * 2048, str(heads / "Asha.jpg")),
    )
    conn.commit()
    with pytest.raises(ValueError):
        export_sorted(conn, str(heads))
    assert (heads / "Asha.jpg").read_bytes() == b"x"


def test_marked_out_dir_containing_the_source_dir(tmp_path):
    # isolates the "output contains the photos" guard: the marker is present, so the
    # unmarked-folder guard cannot be what refuses this
    out = tmp_path / "out"
    conn = _conn_with_photo(out / "photos")
    (out / MARKER).write_text("1")
    with pytest.raises(ValueError, match="inside the output folder"):
        export_sorted(conn, str(out))
    assert (out / "photos" / "a.jpg").exists()
