import json

from convo_gallery import config
from convo_gallery.db import open_db
from convo_gallery.export_web import export
from PIL import Image


def test_export_web_local(tmp_path, monkeypatch):
    data = tmp_path / "data"
    previews, crops = data / "previews", data / "crops"
    previews.mkdir(parents=True)
    crops.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", str(data))
    monkeypatch.setattr(config, "PREVIEWS_DIR", str(previews))
    monkeypatch.setattr(config, "CROPS_DIR", str(crops))
    conn = open_db(":memory:")
    conn.execute("INSERT INTO clusters (id, label, rep_face_id, face_count, media_count) VALUES (1, NULL, 1, 2, 2)")
    for mid, key in ((1, "local-a"), (2, "local-b")):
        Image.new("RGB", (200, 100), (10, 20, 30)).save(previews / f"{key}.jpg")
        Image.new("RGB", (160, 160), (50, 60, 70)).save(crops / f"{key}_0.jpg")
        conn.execute(
            "INSERT INTO media_items (id, drive_file_id, filename, kind, status, source, local_path, dt_utc) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (mid, key, f"{key}.jpg", "jpeg", "processed", "local", f"/x/{key}.jpg", 1000 + mid),
        )
        conn.execute(
            "INSERT INTO faces (id, media_id, bbox, det_score, face_px, embedding, crop_path, cluster_id, is_usable) "
            "VALUES (?,?,?,?,?,?,?,1,1)",
            (mid, mid, "[10,10,50,50]", 0.9, 80, b"\0" * 2048, str(crops / f"{key}_0.jpg")),
        )
    conn.commit()
    out = tmp_path / "web"
    res = export(conn, out_dir=str(out))
    assert res["people"] == 1 and res["mode"] == "local"
    p0 = json.loads((out / "index.json").read_text())["people"][0]
    assert p0["name"] == "person-001" and p0["named"] is False and p0["media_count"] == 2
    photos = json.loads((out / "people" / "1.json").read_text())["photos"]
    assert photos[0]["jpg_url"] == f"/original/{photos[0]['id']}"
    assert photos[0]["view_url"] == photos[0]["jpg_url"]
    assert (out / "thumbs" / f"{photos[0]['id']}.jpg").exists()
