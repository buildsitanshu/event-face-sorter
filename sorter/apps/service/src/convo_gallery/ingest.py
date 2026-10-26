# Ingest: recursively list the Drive folder tree into media_items (idempotent, re-runnable as the
# folder grows). Drive's imageMediaMetadata.time gives EXIF capture time for free (no download);
# videoMediaMetadata.durationMillis gives clip length. Classify each file so the pipeline routes
# photos (thumbnail->faces) vs videos (download->frames->faces) vs skip.
from __future__ import annotations

import time
from collections.abc import Iterator

RAW_EXT = {"cr2", "cr3", "nef", "arw", "raf", "dng", "orf", "rw2", "pef", "srw", "raw"}
JPEG_EXT = {"jpg", "jpeg", "png", "heic", "heif", "webp", "tif", "tiff"}
VIDEO_EXT = {"mp4", "mov", "avi", "mts", "m2ts", "m4v", "mkv", "wmv", "mpg", "mpeg", "3gp"}
FOLDER_MIME = "application/vnd.google-apps.folder"


def classify(name: str, mime: str | None) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    mime = mime or ""
    if mime.startswith("video/") or ext in VIDEO_EXT:
        return "video"
    if ext in RAW_EXT:
        return "raw"
    if ext in JPEG_EXT or mime.startswith("image/"):
        return "jpeg"
    return "other"


def walk(svc, root_id: str) -> Iterator[dict]:
    """Yield every non-folder file under root_id, depth-first, with a '_path' breadcrumb."""
    stack = [(root_id, "")]
    while stack:
        fid, path = stack.pop()
        token = None
        while True:
            resp = svc.files().list(
                q=f"'{fid}' in parents and trashed=false",
                fields="nextPageToken, files(id,name,mimeType,size,modifiedTime,imageMediaMetadata(time),videoMediaMetadata(durationMillis))",
                pageSize=1000, pageToken=token,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute()
            for f in resp.get("files", []):
                if f.get("mimeType") == FOLDER_MIME:
                    stack.append((f["id"], f"{path}/{f['name']}"))
                else:
                    f["_path"] = f"{path}/{f['name']}"
                    yield f
            token = resp.get("nextPageToken")
            if not token:
                break


def ingest(conn, svc, root_id: str) -> dict:
    """Walk the tree, INSERT OR IGNORE each file into media_items. Returns counts + bytes by kind."""
    counts: dict[str, int] = {}
    bytes_by: dict[str, int] = {}
    total = 0
    now = int(time.time())
    for f in walk(svc, root_id):
        kind = classify(f["name"], f.get("mimeType"))
        size = int(f.get("size", 0) or 0)
        counts[kind] = counts.get(kind, 0) + 1
        bytes_by[kind] = bytes_by.get(kind, 0) + size
        dt = (f.get("imageMediaMetadata") or {}).get("time")  # "YYYY:MM:DD HH:MM:SS"
        dur_ms = (f.get("videoMediaMetadata") or {}).get("durationMillis")
        dur = int(dur_ms) / 1000.0 if dur_ms else None
        conn.execute(
            "INSERT OR IGNORE INTO media_items "
            "(drive_file_id, filename, drive_path, size_bytes, mime_type, kind, datetime_original, duration_sec, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?, 'listed', ?)",
            (f["id"], f["name"], f.get("_path"), size, f.get("mimeType"), kind, dt, dur, now),
        )
        total += 1
        if total % 500 == 0:
            conn.commit()
    conn.commit()
    return {"total": total, "by_kind": counts, "bytes_by_kind": bytes_by}
