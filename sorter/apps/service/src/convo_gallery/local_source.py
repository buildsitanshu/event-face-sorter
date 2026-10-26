# Local-folder input: walk a directory of photos/videos (and optionally a directory of headshots)
# instead of a Google Drive folder. Local files are keyed by a stable hash of their relative path,
# stored in media_items.drive_file_id (the column name is historical), so re-ingest is idempotent.
from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Iterator

from PIL import Image, ImageOps

from . import config
from .group_stage import _epoch
from .ingest import classify

try:  # HEIC opens through Pillow when pillow-heif is installed
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # noqa: BLE001, S110
    pass

LOCAL_PREFIX = "local-"


def local_key(relpath: str) -> str:
    return LOCAL_PREFIX + hashlib.sha1(relpath.encode("utf-8")).hexdigest()[:20]


def walk_local(root: str) -> Iterator[dict]:
    """Yield every visible file under root (dot-dirs pruned, dot-files such as macOS "._" skipped)."""
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            abspath = os.path.join(dirpath, name)
            relpath = os.path.relpath(abspath, root).replace(os.sep, "/")
            try:
                size = os.path.getsize(abspath)
            except OSError:
                size = 0
            yield {"relpath": relpath, "abspath": abspath, "name": name, "size": size}


def exif_datetime(path: str) -> str | None:
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            val = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        return str(val)[:19] if val else None
    except Exception:  # noqa: BLE001
        return None


def make_preview(src: str, dst: str, max_px: int = 2048) -> bool:
    tmp = dst + ".tmp"
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((max_px, max_px))
            im.save(tmp, "JPEG", quality=90)
        os.replace(tmp, dst)
        return True
    except Exception:  # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def ingest_local(conn, media_dir: str) -> dict:
    if not os.path.isdir(media_dir):
        raise FileNotFoundError(f"photos folder not found: {media_dir}")
    total = new = 0
    by_kind: dict[str, int] = {}
    for f in walk_local(media_dir):
        kind = classify(f["name"], None)
        by_kind[kind] = by_kind.get(kind, 0) + 1
        total += 1
        dto = exif_datetime(f["abspath"]) if kind == "jpeg" else None
        if kind in ("jpeg", "video"):
            status, err = "listed", None
        elif kind == "raw":
            status, err = "skipped", "local_raw_unsupported"
        else:
            status, err = "skipped", "not_media"
        cur = conn.execute(
            "INSERT OR IGNORE INTO media_items (drive_file_id, filename, drive_path, size_bytes, "
            "mime_type, kind, source, local_path, datetime_original, dt_utc, status, error_msg, created_at) "
            "VALUES (?,?,?,?,NULL,?,'local',?,?,?,?,?,?)",
            (
                local_key(f["relpath"]), f["name"], f["relpath"], f["size"], kind, f["abspath"],
                dto, _epoch(dto), status, err, int(time.time()),
            ),
        )
        if cur.rowcount == 1:
            new += 1
    conn.commit()
    return {"total": total, "by_kind": by_kind, "new": new, "media_dir": os.path.abspath(media_dir)}


def enroll_local(conn, roster_dir: str, *, force: bool = False) -> dict:
    """Enroll headshots from a local folder (mirrors reference.enroll). Filename minus extension
    is the person's name (stored without the extension, because it becomes the folder name)."""
    from lia_face_recognition import config as fr_config
    from lia_face_recognition.embed import detect_and_embed

    from .reference import _blob

    if not os.path.isdir(roster_dir):
        raise FileNotFoundError(f"headshots folder not found: {roster_dir}")
    config.ensure_dirs()
    if force:
        conn.execute("DELETE FROM reference_faces")
        conn.commit()
    existing = conn.execute("SELECT COUNT(*) FROM reference_faces").fetchone()[0]
    if existing:
        return {"enrolled": existing, "skipped": True}
    files = [f for f in walk_local(roster_dir) if classify(f["name"], None) == "jpeg"]
    enrolled = no_face = 0
    for f in files:
        key = local_key(f["relpath"])
        preview = os.path.join(config.PREVIEWS_DIR, f"ref_{key}.jpg")
        if not make_preview(f["abspath"], preview, max_px=1024):
            no_face += 1
            continue
        usable = [x for x in detect_and_embed(preview) if x.is_usable]
        if not usable:
            no_face += 1
            continue
        primary = max(usable, key=lambda x: x.face_px)
        conn.execute(
            "INSERT INTO reference_faces (drive_file_id, filename, embedding, embed_model_tag, local_path) "
            "VALUES (?,?,?,?,?)",
            (key, os.path.splitext(f["name"])[0], _blob(primary.embedding), fr_config.MODEL_TAG, f["abspath"]),
        )
        enrolled += 1
    conn.commit()
    return {"enrolled": enrolled, "no_face": no_face, "total_files": len(files), "model_tag": fr_config.MODEL_TAG}
