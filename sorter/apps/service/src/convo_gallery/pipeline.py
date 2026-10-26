# The processing orchestrator. The PARENT owns the only DB connection (single-writer funnel);
# worker processes do pure compute (download + detect) and return results. Work is claimed in
# batches via the status state-machine, so a kill/re-run resumes exactly where it stopped, and a
# second worker node could later claim disjoint rows with no race.
from __future__ import annotations

import json
import multiprocessing as mp
import time

import numpy as np

from . import config
from .process import process_one


def _emb_blob(embedding) -> bytes:
    return np.asarray(embedding, dtype=np.float32).tobytes()


def _insert_faces(conn, mid: int, faces: list[dict], model_tag: str) -> int:
    for f in faces:
        conn.execute(
            "INSERT INTO faces (media_id, source, frame_index, timecode_sec, bbox, det_score, face_px, blur_var, embedding, embed_model_tag, crop_path, is_usable) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid, f.get("source", "photo"), f.get("frame_index"), f.get("timecode_sec"),
                json.dumps(f["bbox"]), f["det_score"], f["face_px"], f.get("blur_var"),
                _emb_blob(f["embedding"]), model_tag, f.get("crop_path"), 1 if f["is_usable"] else 0,
            ),
        )
    return len(faces)


def _write_result(conn, res: dict) -> int:
    mid = res["media_id"]
    if not res.get("ok"):
        conn.execute(
            "UPDATE media_items SET status='process_error', error_msg=?, attempts=attempts+1 WHERE id=?",
            (res.get("error", "unknown"), mid),
        )
        return 0
    if res.get("preview_path"):
        conn.execute(
            "UPDATE media_items SET preview_path=?, preview_source=? WHERE id=?",
            (res["preview_path"], res.get("preview_source"), mid),
        )
    n = _insert_faces(conn, mid, res.get("faces", []), res.get("model_tag", "unknown"))
    conn.execute("UPDATE media_items SET status='processed', processed_at=? WHERE id=?", (int(time.time()), mid))
    return n


def redetect_photos(conn, *, workers: int = 10, batch: int = 128) -> dict:
    """Re-detect photos on their saved previews at the current det_size/model, REPLACES their faces.
    Resumable: only photos NOT already at the current model are worked, and each is stamped
    media_items.detect_model_tag on success (even with 0 faces), so a kill / power outage resumes
    exactly where it stopped and never redoes a finished photo. No Drive downloads. Skips videos
    (their frames are gone; they're re-processed by the pull)."""
    from lia_face_recognition import config as fr_config

    from .process import redetect_one

    current = fr_config.MODEL_TAG  # the model we are redetecting TO (e.g. antelopev2@cpu)
    ctx = mp.get_context("spawn")
    rows = conn.execute(
        "SELECT id, drive_file_id, preview_path FROM media_items "
        "WHERE kind IN ('raw','jpeg') AND preview_path IS NOT NULL "
        "AND (detect_model_tag IS NULL OR detect_model_tag != ?) ORDER BY id",
        (current,),
    ).fetchall()
    medias = [{"id": r[0], "drive_file_id": r[1], "preview_path": r[2]} for r in rows]
    total = len(medias)
    processed = faces = errors = 0
    with ctx.Pool(workers) as pool:
        for s in range(0, total, batch):
            chunk = medias[s : s + batch]
            for res in pool.imap_unordered(redetect_one, chunk):
                mid = res["media_id"]
                if res.get("ok"):
                    tag = res.get("model_tag", current)
                    conn.execute("DELETE FROM faces WHERE media_id=?", (mid,))  # drop old-model faces
                    faces += _insert_faces(conn, mid, res.get("faces", []), tag)
                    conn.execute("UPDATE media_items SET detect_model_tag=? WHERE id=?", (tag, mid))
                else:
                    errors += 1
                processed += 1
            conn.commit()
            print(f"  ...redetected={processed}/{total} faces={faces} errors={errors}", flush=True)
    return {"redetected": processed, "remaining_at_start": total, "faces": faces, "errors": errors}


def reclaim_unfinished(conn, kinds: tuple[str, ...]) -> int:
    """Return rows a previous run claimed but never finished (crash, power loss, Ctrl-C) to the
    queue, so the next run picks them up. Returns the number of rows reclaimed."""
    placeholders = ",".join("?" for _ in kinds)
    cur = conn.execute(
        f"UPDATE media_items SET status='listed', claimed_by=NULL "
        f"WHERE status='claimed' AND kind IN ({placeholders})",
        kinds,
    )
    conn.commit()
    return cur.rowcount


def run(conn, kinds: tuple[str, ...], *, workers: int = 8, batch: int = 64, node: str = "local", limit: int | None = None) -> dict:
    """Process all 'listed' media of the given kinds. Returns processed + face counts."""
    reclaimed = reclaim_unfinished(conn, kinds)
    if reclaimed:
        print(f"  resumed {reclaimed} file(s) left unfinished by an earlier run", flush=True)
    ctx = mp.get_context("spawn")
    placeholders = ",".join("?" for _ in kinds)
    processed = faces = errors = 0
    # ONE pool for the whole run: each worker loads the face model once, not per batch.
    with ctx.Pool(workers) as pool:
        while True:
            rows = conn.execute(
                f"SELECT id, drive_file_id, filename, kind, duration_sec, source, local_path FROM media_items "
                f"WHERE status='listed' AND kind IN ({placeholders}) ORDER BY id LIMIT ?",
                (*kinds, batch),
            ).fetchall()
            if not rows:
                break
            medias = [
                {
                    "id": r[0], "drive_file_id": r[1], "filename": r[2], "kind": r[3],
                    "duration_sec": r[4], "source": r[5], "local_path": r[6],
                }
                for r in rows
            ]
            ids = [m["id"] for m in medias]
            conn.execute(
                f"UPDATE media_items SET status='claimed', claimed_by=? WHERE id IN ({','.join('?' for _ in ids)})",
                (node, *ids),
            )
            conn.commit()
            for res in pool.imap_unordered(process_one, medias):
                faces += _write_result(conn, res)
                processed += 1
                if not res.get("ok"):
                    errors += 1
            conn.commit()
            print(f"  ...processed={processed} faces={faces} errors={errors} ({int(time.time())})", flush=True)
            if limit and processed >= limit:
                break
    return {"processed": processed, "faces": faces, "errors": errors, "reclaimed": reclaimed}
