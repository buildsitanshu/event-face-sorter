# Per-item processing (runs in a worker process). Photos: Drive thumbnail -> detect+embed faces.
# Videos: download original -> sample frames -> detect+embed per frame (with timecodes), then
# delete the big original + frames (we keep only the small face crops). Each worker builds its own
# Drive client + face model once (module singletons), so neither is pickled across the pool.
from __future__ import annotations

import os

from . import config

_SVC = None
_CREDS = None


def _client():
    global _SVC, _CREDS
    if _SVC is None:
        from .drive import drive_service, make_creds

        _CREDS = make_creds()
        _SVC = drive_service(_CREDS)
    return _SVC, _CREDS


def _crop_face(img_bgr, bbox, out_path, margin: float = 0.3, size: int = 160) -> bool:
    import cv2

    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    mx, my = int(w * margin), int(h * margin)
    H, W = img_bgr.shape[:2]
    cx1, cy1, cx2, cy2 = max(0, x1 - mx), max(0, y1 - my), min(W, x2 + mx), min(H, y2 + my)
    crop = img_bgr[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return False
    crop = cv2.resize(crop, (size, size))
    cv2.imwrite(out_path, crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return True


def _faces_with_crops(image_path: str, crop_prefix: str, extra: dict | None = None) -> list[dict]:
    import cv2

    from lia_face_recognition.embed import detect_and_embed

    faces = detect_and_embed(image_path)
    if not faces:
        return []
    img = cv2.imread(image_path)
    out = []
    for i, f in enumerate(faces):
        crop_path = os.path.join(config.CROPS_DIR, f"{crop_prefix}_{i}.jpg")
        _crop_face(img, f.bbox, crop_path)
        d = f.as_dict()
        d["crop_path"] = crop_path
        if extra:
            d.update(extra)
        out.append(d)
    return out


def process_photo(media: dict) -> dict:
    if media.get("source") == "local":
        from .local_source import make_preview

        key = media["drive_file_id"]
        preview_path = os.path.join(config.PREVIEWS_DIR, f"{key}.jpg")
        if not make_preview(media["local_path"], preview_path):
            return {"error": "unreadable_image"}
        faces = _faces_with_crops(preview_path, key, extra={"source": "photo"})
        return {"preview_path": preview_path, "preview_source": "local_preview", "faces": faces}

    from .drive import download_thumbnail

    svc, creds = _client()
    fid = media["drive_file_id"]
    preview_path = os.path.join(config.PREVIEWS_DIR, f"{fid}.jpg")
    if not download_thumbnail(svc, creds, fid, preview_path, size_px=2048):
        return {"error": "no_thumbnail"}
    faces = _faces_with_crops(preview_path, fid, extra={"source": "photo"})
    return {"preview_path": preview_path, "preview_source": "drive_thumbnail", "faces": faces}


def process_video(media: dict) -> dict:
    import shutil

    from lia_video_frame_reader.frames import sample_frames

    is_local = media.get("source") == "local"
    fid = media["drive_file_id"]
    ext = os.path.splitext(media["filename"])[1] or ".mp4"
    orig = media["local_path"] if is_local else os.path.join(config.ORIGINALS_DIR, f"{fid}{ext}")
    frame_dir = os.path.join(config.FRAMES_DIR, fid)
    faces: list[dict] = []
    try:
        if not is_local:
            from .drive import download_original

            svc, _ = _client()
            download_original(svc, fid, orig)
        frames = sample_frames(orig, frame_dir, fps=config.VIDEO_FPS)
        for fr in frames:
            faces.extend(
                _faces_with_crops(
                    fr.frame_path,
                    f"{fid}_f{fr.index}",
                    extra={"source": "video", "frame_index": fr.index, "timecode_sec": fr.timecode_sec},
                )
            )
    finally:
        # keep only the small crops; drop the big downloaded original + raw frames.
        # A local source file is the user's own and is NEVER deleted.
        if not is_local:
            try:
                os.remove(orig)
            except OSError:
                pass
        shutil.rmtree(frame_dir, ignore_errors=True)
    return {"faces": faces}


def _tag(res: dict) -> dict:
    from lia_face_recognition import config as fr_config

    res["model_tag"] = fr_config.MODEL_TAG  # the worker's ACTUAL model (reflects any fallback)
    return res


def process_one(media: dict) -> dict:
    """Pool entry point. Returns a result dict tagged with media_id + ok/error."""
    try:
        res = process_video(media) if media["kind"] == "video" else process_photo(media)
        res["media_id"] = media["id"]
        res["ok"] = "error" not in res
        return _tag(res)
    except Exception as e:  # any failure becomes a recorded process_error, never a crash  # noqa: BLE001
        return {"media_id": media["id"], "ok": False, "error": repr(e)[:300]}


def redetect_one(media: dict) -> dict:
    """Re-detect a photo on its ALREADY-DOWNLOADED preview (no Drive fetch). Used by the
    accuracy reprocess at the new det_size/model."""
    try:
        preview = media.get("preview_path")
        if not preview or not os.path.exists(preview):
            return {"media_id": media["id"], "ok": False, "error": "no_preview"}
        faces = _faces_with_crops(preview, media["drive_file_id"], extra={"source": "photo"})
        return _tag({"media_id": media["id"], "ok": True, "faces": faces})
    except Exception as e:  # noqa: BLE001
        return {"media_id": media["id"], "ok": False, "error": repr(e)[:300]}
