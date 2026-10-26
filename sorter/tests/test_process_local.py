import inspect
import os

import lia_video_frame_reader.frames as frames
from convo_gallery import config, pipeline, process
from PIL import Image


def test_process_video_local_keeps_source(tmp_path, monkeypatch):
    src = tmp_path / "c.mp4"
    src.write_bytes(b"known-bytes")
    monkeypatch.setattr(config, "FRAMES_DIR", str(tmp_path / "frames"))
    monkeypatch.setattr(frames, "sample_frames", lambda *a, **k: [])
    monkeypatch.setattr(process, "_faces_with_crops", lambda *a, **k: [])
    res = process.process_video({
        "id": 1, "drive_file_id": "local-x", "filename": "c.mp4", "kind": "video",
        "source": "local", "local_path": str(src),
    })
    assert res["faces"] == []
    assert src.exists() and src.read_bytes() == b"known-bytes"


def test_process_photo_local_branch_never_touches_drive(tmp_path, monkeypatch):
    src = tmp_path / "p.jpg"
    Image.new("RGB", (64, 48), (10, 200, 10)).save(src)
    previews = tmp_path / "previews"
    previews.mkdir()
    monkeypatch.setattr(config, "PREVIEWS_DIR", str(previews))

    def no_drive():
        raise AssertionError("a Drive client was constructed for a local photo")

    monkeypatch.setattr(process, "_client", no_drive)
    monkeypatch.setattr(process, "_faces_with_crops", lambda *a, **k: [{"bbox": [1, 1, 9, 9]}])
    res = process.process_photo({
        "id": 2, "drive_file_id": "local-y", "filename": "p.jpg", "kind": "jpeg",
        "source": "local", "local_path": str(src),
    })
    assert os.path.exists(res["preview_path"])
    assert res["preview_source"] == "local_preview"
    assert len(res["faces"]) == 1


def test_pipeline_run_selects_source_and_local_path():
    # STRUCTURAL test: run() hands rows to a spawn pool, so the SELECT is checked in its source
    # text rather than by execution. It guards against dropping the two columns the workers need.
    src = inspect.getsource(pipeline.run)
    assert "source" in src and "local_path" in src
    assert '"source": r[5]' in src and '"local_path": r[6]' in src
