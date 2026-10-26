# Google Drive client + helpers. Reads the OAuth token written by scripts/drive_auth.py (drive.readonly).
# Face detection runs on Drive's small server-side thumbnail (no 26 MB pull); the full original
# is fetched only for videos (to sample frames) and on-demand downloads.
from __future__ import annotations

import json

from .config import OAUTH_PATH, SCOPES


def make_creds():
    from google.oauth2.credentials import Credentials

    raw = json.load(open(OAUTH_PATH))
    info = raw.get("installed") or raw.get("web") or raw
    return Credentials(
        token=info.get("token"),
        refresh_token=info["refresh_token"],
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def drive_service(creds=None):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds or make_creds(), cache_discovery=False)


def _bearer(creds) -> str:
    from google.auth.transport.requests import Request

    if not creds.valid:
        creds.refresh(Request())
    return creds.token


def get_thumbnail_url(svc, file_id: str, size_px: int = 2048) -> str | None:
    meta = svc.files().get(fileId=file_id, fields="thumbnailLink", supportsAllDrives=True).execute()
    link = meta.get("thumbnailLink")
    if not link:
        return None
    if "=s" in link:  # bump Drive's default '=s220' to our detection size
        link = link.rsplit("=s", 1)[0] + f"=s{size_px}"
    return link


def download_thumbnail(svc, creds, file_id: str, dest_path: str, size_px: int = 2048) -> bool:
    """Fetch the Drive thumbnail (bearer-authed) to dest_path. False if Drive has no thumbnail."""
    import httpx

    url = get_thumbnail_url(svc, file_id, size_px)
    if not url:
        return False
    with httpx.stream(
        "GET", url, headers={"Authorization": f"Bearer {_bearer(creds)}"}, timeout=120, follow_redirects=True
    ) as r:
        if r.status_code != 200:
            return False
        with open(dest_path, "wb") as fh:
            for chunk in r.iter_bytes(65536):
                fh.write(chunk)
    return True


def download_original(svc, file_id: str, dest_path: str) -> None:
    """Stream the full original file (videos + on-demand RAW downloads)."""
    from googleapiclient.http import MediaIoBaseDownload

    req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req, chunksize=16 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
