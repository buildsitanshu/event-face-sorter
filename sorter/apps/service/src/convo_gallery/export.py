# Static gallery generator: the sendable artifact. Renders, from the DB, a people grid + one page
# per person listing their photos/videos, each as a small face crop linking to the Drive
# direct-download URL (originals stay on Drive; we host only tiny crops). Host the output dir as one
# URL and share it; everyone finds their face and downloads their own files from Drive.
# This is the functional v1 export; the gallery viewer is the FastAPI app (api.py).
from __future__ import annotations

import html
import os
import shutil

from . import config
from .links import drive_download_url, drive_view_url

_CSS = """
:root{--bg:#0f1115;--card:#181b22;--line:#262b36;--text:#e6e8ee;--dim:#9aa3b2;--accent:#6ea8fe}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{padding:20px 24px;border-bottom:1px solid var(--line)}
h1{font-size:20px;margin:0}.sub{color:var(--dim);font-size:13px;margin-top:4px}
.wrap{padding:20px 24px;max-width:1200px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;text-align:center}
.card img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:#222}
.card .meta{padding:8px 6px;font-size:12px;color:var(--dim)}
.media{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
.m{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.m img{width:100%;aspect-ratio:1;object-fit:cover;background:#222}
.m .r{padding:8px;font-size:12px}.m .r .fn{color:var(--text);word-break:break-all}
.tag{display:inline-block;font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:6px;padding:1px 6px}
.dl{display:inline-block;margin-top:6px;font-weight:600}
"""


def _w(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _copy_crop(src: str | None, crops_out: str) -> str | None:
    if not src or not os.path.exists(src):
        return None
    base = os.path.basename(src)
    dst = os.path.join(crops_out, base)
    if not os.path.exists(dst):
        shutil.copyfile(src, dst)
    return f"crops/{base}"


def export_gallery(conn, out_dir: str | None = None, *, include_unknown: bool = False) -> dict:
    out_dir = out_dir or os.path.join(config.DATA_DIR, "gallery")
    crops_out = os.path.join(out_dir, "crops")
    os.makedirs(crops_out, exist_ok=True)

    # roster people who actually appear in >=1 photo/video (hide empty + non-roster)
    where = "WHERE media_count > 0" + ("" if include_unknown else " AND is_unknown=0")
    people = conn.execute(
        f"SELECT id, rep_face_id, face_count, media_count, is_unknown FROM clusters {where} "
        "ORDER BY is_unknown ASC, media_count DESC, face_count DESC"
    ).fetchall()

    cards = []
    n_pages = 0
    for cid, rep_face_id, face_count, media_count, is_unknown in people:
        rep_src = conn.execute("SELECT crop_path FROM faces WHERE id=?", (rep_face_id,)).fetchone()
        rep_rel = _copy_crop(rep_src[0] if rep_src else None, crops_out)
        # this person's media
        media = conn.execute(
            "SELECT DISTINCT m.id, m.drive_file_id, m.filename, m.size_bytes, m.kind "
            "FROM faces f JOIN media_items m ON m.id=f.media_id "
            "WHERE f.cluster_id=? AND f.is_usable=1 ORDER BY m.kind, m.filename",
            (cid,),
        ).fetchall()
        n_photos = sum(1 for x in media if x[4] != "video")
        n_videos = sum(1 for x in media if x[4] == "video")

        tiles = []
        for mid, fileid, fname, size, kind in media:
            crop_row = conn.execute(
                "SELECT crop_path, source, timecode_sec FROM faces WHERE cluster_id=? AND media_id=? ORDER BY det_score DESC LIMIT 1",
                (cid, mid),
            ).fetchone()
            crop_rel = _copy_crop(crop_row[0] if crop_row else None, crops_out)
            tc = crop_row[2] if crop_row else None
            badge = f"<span class='tag'>video{f' · {int(tc)}s' if tc is not None else ''}</span>" if kind == "video" else ""
            img = f"<img loading='lazy' src='{crop_rel}'>" if crop_rel else "<img>"
            tiles.append(
                f"<div class='m'>{img}<div class='r'><div class='fn'>{html.escape(fname)}</div>{badge}"
                f"<br><a class='dl' href='{drive_download_url(fileid, size or 0)}'>Download</a> · "
                f"<a href='{drive_view_url(fileid)}' target='_blank'>view</a></div></div>"
            )

        page = (
            f"<!doctype html><meta charset=utf-8><title>Person {cid}</title><style>{_CSS}</style>"
            f"<header><h1><a href='index.html'>← all people</a> &nbsp; Person {cid}</h1>"
            f"<div class='sub'>{n_photos} photos · {n_videos} videos</div></header>"
            f"<div class='wrap'><div class='media'>{''.join(tiles)}</div></div>"
        )
        _w(os.path.join(out_dir, f"person_{cid}.html"), page)
        n_pages += 1

        img = f"<img loading='lazy' src='{rep_rel}'>" if rep_rel else "<img>"
        cards.append(
            f"<a class='card' href='person_{cid}.html'>{img}"
            f"<div class='meta'>Person {cid}<br>{n_photos}p · {n_videos}v</div></a>"
        )

    index = (
        f"<!doctype html><meta charset=utf-8><title>Photo Gallery</title><style>{_CSS}</style>"
        f"<header><h1>Photo Gallery</h1><div class='sub'>{len(people)} people · tap a face to see and download their photos &amp; videos</div></header>"
        f"<div class='wrap'><div class='grid'>{''.join(cards)}</div></div>"
    )
    _w(os.path.join(out_dir, "index.html"), index)
    return {"out_dir": out_dir, "people": len(people), "pages": n_pages, "index": os.path.join(out_dir, "index.html")}
