# Drive link helpers. The originals stay on the public Drive; we never re-host them. A download
# "link" is just the Drive direct-download URL for a file id (works because the folder is shared
# anyone-with-link). Files >~100 MB (videos) need &confirm=t to skip Drive's scan interstitial.
from __future__ import annotations

LARGE_FILE_BYTES = 100 * 1024 * 1024


def drive_view_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def drive_download_url(file_id: str, size_bytes: int = 0) -> str:
    base = f"https://drive.google.com/uc?export=download&id={file_id}"
    return base + "&confirm=t" if size_bytes >= LARGE_FILE_BYTES else base
