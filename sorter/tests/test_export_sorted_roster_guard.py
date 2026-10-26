import pytest
from convo_gallery.db import open_db
from convo_gallery.export_sorted import MARKER, export_sorted


def _conn_with_headshot(heads):
    heads.mkdir(parents=True)
    (heads / "Asha.jpg").write_bytes(b"x")
    conn = open_db(":memory:")
    conn.execute(
        "INSERT INTO reference_faces (drive_file_id, filename, embedding, embed_model_tag, local_path) "
        "VALUES ('local-h','Asha',?,'t',?)",
        (b"\0" * 2048, str(heads / "Asha.jpg")),
    )
    conn.commit()
    return conn


def test_marked_headshot_dir_is_refused_as_output(tmp_path):
    # the dir carries the marker, so the unmarked-folder guard cannot be the one refusing
    heads = tmp_path / "heads"
    conn = _conn_with_headshot(heads)
    (heads / MARKER).write_text("1")
    with pytest.raises(ValueError, match="inside the photo folder") as ei:
        export_sorted(conn, str(heads))
    assert str(heads.resolve()) in str(ei.value)
    assert (heads / "Asha.jpg").read_bytes() == b"x"


def test_marked_output_containing_the_headshot_dir_is_refused(tmp_path):
    out = tmp_path / "out"
    conn = _conn_with_headshot(out / "heads")
    (out / MARKER).write_text("1")
    with pytest.raises(ValueError, match="inside the output folder"):
        export_sorted(conn, str(out))
    assert (out / "heads" / "Asha.jpg").read_bytes() == b"x"
