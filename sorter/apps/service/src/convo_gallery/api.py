# FastAPI surface for the gallery (local viewer). people/person/query power the grid + selection;
# /original serves a local original (or redirects to Drive); / serves the exported gallery page from
# data/web. Crops are served as small static files. The query path is the SAME query_media_ids the
# download uses, so the previewed set and the downloaded set can't disagree.
from __future__ import annotations

import os
import tempfile
import zipfile

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.background import BackgroundTask

from . import __version__, config
from .db import open_db
from .export_sorted import folder_name
from .links import drive_download_url, drive_view_url
from .query.people import query_media_ids

app = FastAPI(title="event-face-sorter", version=__version__)


def conn():
    c = open_db(config.DB_PATH)
    try:
        yield c
    finally:
        c.close()


DB = Depends(conn)  # module-level so route signatures stay free of calls (ruff B008)


def _urls(source, media_id, drive_file_id, size_bytes) -> tuple[str, str]:
    """(download_url, view_url): the local /original route for local rows, Drive links otherwise."""
    if source == "local":
        return f"/original/{media_id}?download=1", f"/original/{media_id}"
    return drive_download_url(drive_file_id, size_bytes or 0), drive_view_url(drive_file_id)


@app.get("/")
def home():
    index = os.path.join(config.WEB_DIR, "index.html")
    if os.path.exists(index):
        return RedirectResponse("/web/", status_code=307)
    return JSONResponse({
        "message": "gallery not exported yet: run ./run.sh (or the export-web command)",
        "api": "/api/people",
    })


@app.get("/original/{media_id}")
def original(media_id: int, download: int = 0, c=DB):
    row = c.execute(
        "SELECT source, local_path, drive_file_id, filename, size_bytes FROM media_items WHERE id=?", (media_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404)
    source, local_path, drive_id, filename, size = row
    if source == "local":
        if not local_path or not os.path.exists(local_path):
            raise HTTPException(404)
        return FileResponse(
            local_path, filename=filename, content_disposition_type="attachment" if download else "inline"
        )
    return RedirectResponse(drive_download_url(drive_id, size or 0))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "tool": "event-face-sorter", "version": __version__}


@app.get("/api/people")
def api_people(min_photos: int = config.MIN_PHOTOS, c=DB) -> JSONResponse:
    rows = c.execute(
        "SELECT id, label, rep_face_id, face_count, media_count, is_unknown FROM clusters "
        "WHERE media_count >= ? ORDER BY media_count DESC, face_count DESC",
        (min_photos,),
    ).fetchall()
    people = [
        {"cluster_id": cid, "label": label, "name": folder_name(label, cid), "rep_face_url": f"/thumb/{rep}",
         "face_count": fc, "media_count": mc, "is_unknown": bool(u)}
        for cid, label, rep, fc, mc, u in rows
    ]
    return JSONResponse({"people": people, "total": len(people)})


@app.get("/api/people/{cluster_id}")
def api_person(cluster_id: int, c=DB) -> JSONResponse:
    rows = c.execute(
        "SELECT DISTINCT m.id, m.drive_file_id, m.filename, m.size_bytes, m.kind, m.source "
        "FROM faces f JOIN media_items m ON m.id=f.media_id WHERE f.cluster_id=? AND f.is_usable=1 "
        "ORDER BY m.kind, m.filename",
        (cluster_id,),
    ).fetchall()
    media = []
    for mid, fileid, fname, size, kind, source in rows:
        dl, view = _urls(source, mid, fileid, size)
        tc = c.execute(
            "SELECT crop_path, timecode_sec FROM faces WHERE cluster_id=? AND media_id=? ORDER BY det_score DESC LIMIT 1",
            (cluster_id, mid),
        ).fetchone()
        media.append({
            "media_id": mid, "filename": fname, "kind": kind, "size_bytes": size,
            "thumb_url": f"/thumb_media/{cluster_id}/{mid}",
            "download_url": dl,
            "view_url": view,
            "timecode_sec": tc[1] if tc else None,
        })
    return JSONResponse({"cluster_id": cluster_id, "count": len(media), "media": media})


@app.get("/api/people/{cluster_id}/companions")
def api_companions(cluster_id: int, c=DB) -> JSONResponse:
    """Ranked companion CANDIDATES for a named person, the people to ask 'did you come with them?'. Only
    meaningful for a named person (is_unknown=0); unknown clusters get an empty list. Each candidate
    carries its current confirmation decision so the UI can show the toggle state."""
    rows = c.execute(
        "SELECT cc.cand_cluster, cl.rep_face_id, cc.co_photos, cc.intimate_photos, cc.burst_photos, "
        "       cc.bucket, cc.rank, cl.is_unknown, conf.decision "
        "FROM companion_candidates cc JOIN clusters cl ON cl.id=cc.cand_cluster "
        "LEFT JOIN companion_confirmations conf ON conf.grad_cluster=cc.grad_cluster AND conf.cand_cluster=cc.cand_cluster "
        "WHERE cc.grad_cluster=? ORDER BY cc.rank",
        (cluster_id,),
    ).fetchall()
    companions = [
        {
            "cluster_id": cand, "rep_face_url": f"/thumb/{rep}", "shared_count": co,
            "intimate_count": intimate, "burst_count": burst, "bucket": bucket, "rank": rank,
            "is_graduate": not bool(u), "decision": decision,  # 'yes' | 'no' | None
        }
        for cand, rep, co, intimate, burst, bucket, rank, u, decision in rows
    ]
    return JSONResponse({"grad_cluster": cluster_id, "companions": companions, "total": len(companions)})


@app.post("/api/people/{cluster_id}/confirm")
def api_confirm(cluster_id: int, payload: dict, c=DB) -> JSONResponse:
    """The human ground-truth write: a named person confirms ('yes') or rejects ('no') a suggested companion."""
    from .companions import confirm

    cand = payload.get("cand_cluster")
    decision = payload.get("decision")
    if not isinstance(cand, int) or decision not in ("yes", "no"):
        raise HTTPException(status_code=400, detail="need {cand_cluster:int, decision:'yes'|'no'}")
    return JSONResponse(confirm(c, cluster_id, cand, decision))


@app.get("/api/people/{cluster_id}/album")
def api_album(cluster_id: int, c=DB) -> JSONResponse:
    """The final personalised album: every photo the named person OR any CONFIRMED companion appears in.
    Thumb per photo uses the named person's crop when present, else a confirmed companion's."""
    from .companions import album_clusters, album_media_ids

    clusters = album_clusters(c, cluster_id)  # [named person, ...confirmed companions]
    media_ids = album_media_ids(c, cluster_id)
    media = []
    for mid in media_ids:
        # pick the crop cluster: prefer the named person, else the first album cluster present in this photo
        present = [cl for cl in clusters if c.execute(
            "SELECT 1 FROM faces WHERE media_id=? AND cluster_id=? AND is_usable=1 LIMIT 1", (mid, cl)
        ).fetchone()]
        crop_cluster = present[0] if present else cluster_id
        row = c.execute(
            "SELECT m.drive_file_id, m.filename, m.size_bytes, m.kind, m.source FROM media_items m WHERE m.id=?", (mid,)
        ).fetchone()
        if not row:
            continue
        fileid, fname, size, kind, source = row
        dl, view = _urls(source, mid, fileid, size)
        media.append({
            "media_id": mid, "filename": fname, "kind": kind, "size_bytes": size,
            "thumb_url": f"/thumb_media/{crop_cluster}/{mid}",
            "download_url": dl,
            "view_url": view,
        })
    return JSONResponse({
        "grad_cluster": cluster_id,
        "companion_clusters": clusters[1:],
        "count": len(media),
        "media": media,
    })


@app.post("/api/query")
def api_query(payload: dict, c=DB) -> JSONResponse:
    ids = query_media_ids(
        c, payload.get("clusters", []), mode=payload.get("mode", "any"),
        session_id=payload.get("session_id"), dt_from=payload.get("dt_from"), dt_to=payload.get("dt_to"),
    )
    return JSONResponse({"media_ids": ids, "total": len(ids)})


@app.get("/api/download/manifest/{cluster_id}")
def download_manifest(cluster_id: int, c=DB) -> JSONResponse:
    """Zero-bandwidth option: the list of Drive direct-download links for this person's media."""
    rows = c.execute(
        "SELECT DISTINCT m.source, m.id, m.drive_file_id, m.filename, m.size_bytes FROM faces f JOIN media_items m ON m.id=f.media_id "
        "WHERE f.cluster_id=? AND f.is_usable=1",
        (cluster_id,),
    ).fetchall()
    return JSONResponse({
        "cluster_id": cluster_id,
        "files": [
            {"filename": n, "download_url": _urls(src, mid, fid, s)[0]} for src, mid, fid, n, s in rows
        ],
    })


@app.get("/thumb/{face_id}")
def thumb(face_id: int, c=DB):
    row = c.execute("SELECT crop_path FROM faces WHERE id=?", (face_id,)).fetchone()
    if not row or not row[0] or not os.path.exists(row[0]):
        raise HTTPException(404)
    return FileResponse(row[0], media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/thumb_media/{cluster_id}/{media_id}")
def thumb_media(cluster_id: int, media_id: int, c=DB):
    row = c.execute(
        "SELECT crop_path FROM faces WHERE cluster_id=? AND media_id=? ORDER BY det_score DESC LIMIT 1",
        (cluster_id, media_id),
    ).fetchone()
    if not row or not row[0] or not os.path.exists(row[0]):
        raise HTTPException(404)
    return FileResponse(row[0], media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/web/{path:path}")
def web(path: str):
    """Serve the exported bundle. WEB_DIR is resolved per request so a CONVO_DATA_DIR override works."""
    try:
        root = os.path.realpath(config.WEB_DIR)
        target = os.path.realpath(os.path.join(root, path)) if path and not path.endswith("/") else None
        if target is None:
            target = os.path.join(root, path, "index.html") if path else os.path.join(root, "index.html")
            target = os.path.realpath(target)
        inside = target == root or target.startswith(root + os.sep)
        is_file = inside and os.path.isfile(target)
    except ValueError:  # embedded NUL byte in the path: a bad request is a 404, not a 500
        raise HTTPException(404) from None
    if not is_file:
        raise HTTPException(404)
    return FileResponse(target)


@app.post("/api/people/{cluster_id}/label")
def api_label(cluster_id: int, payload: dict, c=DB) -> JSONResponse:
    """Rename a person. Empty label clears it (the name falls back to person-NNN)."""
    raw = payload.get("label")
    if raw is not None and not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="need {label:str}")
    label = (raw or "").strip()[:80] or None
    cur = c.execute("UPDATE clusters SET label=? WHERE id=?", (label, cluster_id))
    if cur.rowcount == 0:
        raise HTTPException(404)
    c.commit()
    return JSONResponse({"cluster_id": cluster_id, "label": label, "name": folder_name(label, cluster_id)})


@app.get("/zip/{cluster_id}")
def zip_person(cluster_id: int, c=DB):
    """One zip of every local original the person appears in; Drive items go in drive-links.txt."""
    rows = c.execute(
        "SELECT DISTINCT m.id, m.source, m.local_path, m.drive_file_id, m.filename, m.size_bytes "
        "FROM faces f JOIN media_items m ON m.id=f.media_id WHERE f.cluster_id=? AND f.is_usable=1 "
        "ORDER BY m.filename, m.id",
        (cluster_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(404)
    label = c.execute("SELECT label FROM clusters WHERE id=?", (cluster_id,)).fetchone()
    name = folder_name(label[0] if label else None, cluster_id)
    counts: dict[str, int] = {}
    for _, _, _, _, fname, _ in rows:
        counts[fname] = counts.get(fname, 0) + 1
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    drive_lines: list[str] = []
    missing: list[str] = []
    added = 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
            for mid, source, local_path, fid, fname, size in rows:
                if source == "local":
                    if local_path and os.path.exists(local_path):
                        zf.write(local_path, f"{mid}_{fname}" if counts[fname] > 1 else fname)
                        added += 1
                    else:
                        missing.append(fname)
                else:
                    drive_lines.append(f"{fname}\t{drive_download_url(fid, size or 0)}")
            if drive_lines:
                zf.writestr("drive-links.txt", "\n".join(drive_lines) + "\n")
                added += 1
            if missing and added:
                zf.writestr("missing.txt", "These originals were not found on disk:\n" + "\n".join(missing) + "\n")
        if not added:
            raise HTTPException(404, detail="no originals found on disk for this person")
    except BaseException:
        os.remove(tmp)
        raise
    return FileResponse(
        tmp, media_type="application/zip", filename=f"{name}.zip", background=BackgroundTask(os.remove, tmp),
        headers={"X-Missing-Count": str(len(missing))},
    )
