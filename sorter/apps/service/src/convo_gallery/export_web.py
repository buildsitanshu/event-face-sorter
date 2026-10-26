# Bake the gallery into a static bundle (JSON + thumbnails) that the local viewer (api.py serving
# data/web/index.html) or any static host can render. Reads gallery.db DIRECTLY and single-threaded,
# so the FastAPI threadpool/SQLite issue is irrelevant. Originals are never copied: local items point
# at the API's /original/<media_id> route, Drive items at their Drive download URLs.
#
# Output tree (default data/web/):
#   index.json                  -> the people grid (people seen in at least MIN_PHOTOS photos)
#   people/{cluster_id}.json    -> one entry per DISTINCT photo the person is in (JPG+RAW deduped),
#                                  with original URLs, the 512px thumb, and the face-centre fraction
#   companions/{person}.json    -> ranked companion candidates (from companion_candidates)
#   thumbs/{media_id}.jpg       -> 512px photo preview (grid tiles; faces framed via the fraction)
#   crops/{face_id}.jpg         -> 160px face crop (people-grid avatars + companion chips)
from __future__ import annotations

import json
import os
import shutil

from . import config
from .db import open_db
from .export_sorted import folder_name
from .links import drive_download_url, drive_view_url

THUMB_PX = 512


def _base(filename: str) -> str:
    return os.path.splitext(filename or "")[0]


def _resize(src: str, dst: str, px: int = THUMB_PX) -> None:
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((px, px))
        im.save(dst, "JPEG", quality=80)


def _copy_viewer(out_dir: str) -> bool:
    """Copy the dependency-free viewer (index.html, tokens.css, app.js) next to the JSON, every export."""
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")
    for name in ("index.html", "tokens.css", "app.js"):
        shutil.copyfile(os.path.join(src_dir, name), os.path.join(out_dir, name))
    return True


def export(
    conn, out_dir: str | None = None, *, thumb_px: int = THUMB_PX, min_photos: int = config.MIN_PHOTOS
) -> dict:
    from PIL import Image

    out_dir = out_dir or config.WEB_DIR
    thumbs_d = os.path.join(out_dir, "thumbs")
    crops_d = os.path.join(out_dir, "crops")
    people_d = os.path.join(out_dir, "people")
    comp_d = os.path.join(out_dir, "companions")
    for d in (out_dir, thumbs_d, crops_d, people_d, comp_d):
        os.makedirs(d, exist_ok=True)

    # preview pixel dims are cached so we open each preview at most once for normalisation
    dims_cache: dict[str, tuple[int, int]] = {}

    def dims(path: str) -> tuple[int, int]:
        if path not in dims_cache:
            with Image.open(path) as im:
                dims_cache[path] = im.size  # (w, h)
        return dims_cache[path]

    made_thumbs: set[int] = set()

    def make_thumb(media_id: int, preview_path: str) -> str | None:
        if not preview_path or not os.path.exists(preview_path):
            return None
        dst = os.path.join(thumbs_d, f"{media_id}.jpg")
        if media_id not in made_thumbs:
            _resize(preview_path, dst, thumb_px)
            made_thumbs.add(media_id)
        return f"thumbs/{media_id}.jpg"

    made_crops: set[int] = set()

    def copy_crop(face_id: int | None) -> str | None:
        if not face_id:
            return None
        row = conn.execute("SELECT crop_path FROM faces WHERE id=?", (face_id,)).fetchone()
        if not row or not row[0]:
            return None
        # DB stores a stale absolute crop path (pre-relocation); the file lives in the current
        # crops dir under the same basename (<drive_id>_<i>.jpg).
        src = os.path.join(config.CROPS_DIR, os.path.basename(row[0]))
        if not os.path.exists(src):
            return None
        dst = os.path.join(crops_d, f"{face_id}.jpg")
        if face_id not in made_crops:
            shutil.copyfile(src, dst)
            made_crops.add(face_id)
        return f"crops/{face_id}.jpg"

    def person_photos(cluster_id: int) -> list[dict]:
        """Distinct photos a cluster appears in, deduped across JPG/RAW siblings + scan duplicates.
        Prefer a JPEG (with a preview) for display; keep the RAW sibling only as a download option."""
        rows = conn.execute(
            "SELECT f.id, f.media_id, m.drive_file_id, m.filename, m.kind, m.preview_path, f.bbox, f.det_score, m.dt_utc, m.source "
            "FROM faces f JOIN media_items m ON m.id=f.media_id "
            "WHERE f.cluster_id=? AND f.is_usable=1 AND m.kind IN ('raw','jpeg')",
            (cluster_id,),
        ).fetchall()
        groups: dict[str, dict] = {}
        for face_id, mid, drive_id, fname, kind, preview, bbox_json, det, dt_utc, src in rows:
            key = _base(fname)
            g = groups.setdefault(key, {"jpeg": None, "raw": None, "base": key})
            # derive the preview path from the CURRENT previews dir + drive id (the DB stores a stale
            # absolute path from before the tool was relocated; the file is named <drive_id>.jpg).
            entry = {"face_id": face_id, "mid": mid, "drive_id": drive_id, "fname": fname,
                     "preview": os.path.join(config.PREVIEWS_DIR, f"{drive_id}.jpg"),
                     "bbox": bbox_json, "det": det or 0.0, "dt": dt_utc, "source": src}
            slot = "jpeg" if kind == "jpeg" else "raw"
            # keep the highest-det_score representative per (base, kind)
            if g[slot] is None or entry["det"] > g[slot]["det"]:
                g[slot] = entry

        photos = []
        for key, g in groups.items():
            disp = g["jpeg"] or g["raw"]  # prefer the jpeg as the display/thumbnail source
            if disp is None:
                continue
            thumb = make_thumb(disp["mid"], disp["preview"]) if disp["preview"] else None
            # face-centre as a fraction of the preview (drives CSS object-position so the face stays framed)
            cx = cy = 0.5
            if disp["preview"] and os.path.exists(disp["preview"]):
                try:
                    x1, y1, x2, y2 = json.loads(disp["bbox"])
                    w, h = dims(disp["preview"])
                    cx = min(1.0, max(0.0, ((x1 + x2) / 2) / w))
                    cy = min(1.0, max(0.0, ((y1 + y2) / 2) / h))
                except Exception:  # a bad bbox just falls back to centre framing  # noqa: BLE001
                    pass
            jpg = g["jpeg"]
            raw = g["raw"]
            shown = jpg or disp
            if shown["source"] == "local":
                jpg_url = f"/original/{jpg['mid']}" if jpg else None
                raw_url = f"/original/{raw['mid']}" if raw else None
                view_url = f"/original/{shown['mid']}"
            else:
                jpg_url = drive_download_url(jpg["drive_id"], 0) if jpg else None
                raw_url = drive_download_url(raw["drive_id"], 0) if raw else None
                view_url = drive_view_url(shown["drive_id"])
            photos.append({
                "id": disp["mid"],
                "name": (jpg or disp)["fname"],
                "kind": "photo",
                "thumb": thumb,
                "face": [round(cx, 4), round(cy, 4)],
                "dt": disp["dt"],  # capture time (unix seconds) for chronological ordering
                "jpg_url": jpg_url,
                "raw_url": raw_url,
                "view_url": view_url,
            })

        # videos: one entry per clip the person appears in. A video has no 512px preview, so the tile
        # shows the person's best face-crop frame; the "download" is the video file itself.
        vid_rows = conn.execute(
            "SELECT f.id, m.id, m.drive_file_id, m.filename, f.det_score, m.dt_utc, m.source "
            "FROM faces f JOIN media_items m ON m.id=f.media_id "
            "WHERE f.cluster_id=? AND f.is_usable=1 AND m.kind='video'",
            (cluster_id,),
        ).fetchall()
        best_vid: dict[int, dict] = {}
        for vface_id, vmid, vdrive_id, vfname, vdet, vdt, vsrc in vid_rows:
            cur = best_vid.get(vmid)
            if cur is None or (vdet or 0.0) > cur["det"]:
                best_vid[vmid] = {"face_id": vface_id, "drive_id": vdrive_id, "fname": vfname,
                                  "det": vdet or 0.0, "dt": vdt, "source": vsrc}
        for vmid, v in best_vid.items():
            if v["source"] == "local":
                vjpg_url = vview_url = f"/original/{vmid}"
            else:
                vjpg_url = drive_download_url(v["drive_id"], 0)  # the video file itself
                vview_url = drive_view_url(v["drive_id"])
            photos.append({
                "id": vmid, "name": v["fname"], "kind": "video",
                "thumb": copy_crop(v["face_id"]), "face": [0.5, 0.5], "dt": v["dt"],
                "jpg_url": vjpg_url,
                "raw_url": None,
                "view_url": vview_url,
            })

        # chronological by capture time; any undated item sinks to the end
        photos.sort(key=lambda p: (p["dt"] is None, p["dt"] or 0))
        return photos

    # --- the people grid + per-person photo lists ---
    people_rows = conn.execute(
        "SELECT id, rep_face_id, label, face_count, media_count FROM clusters "
        "WHERE face_count > 0 AND media_count >= ? ORDER BY media_count DESC, face_count DESC",
        (min_photos,),
    ).fetchall()
    index = []
    for cid, rep, label, fc, mc in people_rows:
        photos = person_photos(cid)
        name = folder_name(label, cid)
        with open(os.path.join(people_d, f"{cid}.json"), "w", encoding="utf-8") as fh:
            json.dump({"cluster_id": cid, "name": name, "named": bool(label), "rep_crop": copy_crop(rep),
                       "photo_count": len(photos), "photos": photos}, fh)
        index.append({"cluster_id": cid, "label": label, "name": name, "named": bool(label),
                      "media_count": mc, "rep_crop": copy_crop(rep), "face_count": fc,
                      "photo_count": len(photos)})

    # --- companions: ranked candidates per named person (+ their photo lists so the album can union) ---
    comp_clusters: set[int] = set()
    for cid, *_ in people_rows:
        # "Who came with you" = ONLY people OUTSIDE the named people (is_unknown=1): friends / family /
        # guests. Other named people are excluded. Ranked by NUMBER OF PHOTOS TOGETHER (co_photos desc).
        rows = conn.execute(
            "SELECT cc.cand_cluster, cl.rep_face_id, cl.is_unknown, cc.co_photos, cc.intimate_photos, cc.bucket "
            "FROM companion_candidates cc JOIN clusters cl ON cl.id=cc.cand_cluster "
            "WHERE cc.grad_cluster=? AND cl.is_unknown=1 "
            "ORDER BY cc.co_photos DESC, cc.intimate_photos DESC, cc.cand_cluster",
            (cid,),
        ).fetchall()
        cands = []
        for cand, rep, is_unknown, co, intimate, bucket in rows:
            comp_clusters.add(cand)
            cands.append({"cluster_id": cand, "rep_crop": copy_crop(rep), "shared_count": co,
                          "intimate_count": intimate, "bucket": bucket, "is_graduate": False})
        with open(os.path.join(comp_d, f"{cid}.json"), "w", encoding="utf-8") as fh:
            json.dump({"grad_cluster": cid, "companions": cands}, fh)

    # candidate clusters need their own photo list too (for the client-side album union on confirm)
    for cand in comp_clusters:
        p = os.path.join(people_d, f"{cand}.json")
        if not os.path.exists(p):  # not already written as a named person
            photos = person_photos(cand)
            rep = conn.execute("SELECT rep_face_id FROM clusters WHERE id=?", (cand,)).fetchone()
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({"cluster_id": cand, "rep_crop": copy_crop(rep[0] if rep else None),
                           "photo_count": len(photos), "photos": photos}, fh)

    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"people": index, "total": len(index), "thumb_px": thumb_px}, fh)

    sources = {r[0] for r in conn.execute("SELECT DISTINCT source FROM media_items")}
    mode = "empty" if not sources else "local" if sources == {"local"} else "drive" if sources == {"drive"} else "mixed"
    return {
        "out_dir": out_dir,
        "mode": mode,
        "people": len(index),
        "companion_clusters": len(comp_clusters),
        "thumbs": len(made_thumbs),
        "crops": len(made_crops),
        "viewer": _copy_viewer(out_dir),
    }


if __name__ == "__main__":
    import json as _json

    conn = open_db(config.DB_PATH)
    print(_json.dumps(export(conn), indent=2))
