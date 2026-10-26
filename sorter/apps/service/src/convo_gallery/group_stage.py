# Grouping + sessionizing: the barrier stages that turn faces into people and media into events.
# group_all() clusters ALL usable embeddings at once (a fresh, non-destructive run), assigns each
# face a person, picks a representative crop, and denormalizes counts. sessionize() buckets media
# by EXIF time gaps. Faces from photos AND video frames land in the same people.
from __future__ import annotations

import time
from collections import defaultdict

import numpy as np

from . import config


def group_all(conn, *, threshold: float = 0.35, seed: int = 0) -> dict:
    from lia_face_recognition.group import group_faces

    rows = conn.execute("SELECT id, embedding FROM faces WHERE is_usable=1 ORDER BY id").fetchall()
    if not rows:
        return {"clusters": 0, "faces": 0}
    face_ids = [r[0] for r in rows]
    embs = [np.frombuffer(r[1], dtype=np.float32) for r in rows]
    res = group_faces(embs, threshold=threshold, seed=seed)
    labels, reps = res["labels"], res["representatives"]

    # fresh run: detach faces, drop old clusters (FK-safe order)
    conn.execute("UPDATE faces SET cluster_id=NULL")
    conn.execute("DELETE FROM clusters")

    label_to_faces: dict[int, list[int]] = defaultdict(list)
    for fid, lab in zip(face_ids, labels):
        label_to_faces[lab].append(fid)

    now = int(time.time())
    label_to_cluster: dict[int, int] = {}
    for lab, fids in label_to_faces.items():
        rep_face_id = face_ids[reps[lab]]
        cur = conn.execute(
            "INSERT INTO clusters (label, rep_face_id, face_count, is_unknown, cluster_run_id, created_at) "
            "VALUES (NULL,?,?,?,1,?)",
            (rep_face_id, len(fids), 1 if len(fids) == 1 else 0, now),
        )
        label_to_cluster[lab] = cur.lastrowid

    for fid, lab in zip(face_ids, labels):
        conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (label_to_cluster[lab], fid))
    conn.execute(
        "UPDATE clusters SET media_count = "
        "(SELECT COUNT(DISTINCT media_id) FROM faces WHERE faces.cluster_id = clusters.id)"
    )
    conn.commit()
    n_people = sum(1 for fids in label_to_faces.values() if len(fids) > 1)
    return {"clusters": len(label_to_faces), "people_multi": n_people, "faces": len(face_ids)}


def _epoch(dt_original: str | None) -> int | None:
    # EXIF "YYYY:MM:DD HH:MM:SS" (naive local). None -> undated.
    if not dt_original:
        return None
    try:
        import calendar
        import datetime as _dt

        t = _dt.datetime.strptime(dt_original[:19], "%Y:%m:%d %H:%M:%S")
        return int(calendar.timegm(t.timetuple()))
    except (ValueError, TypeError):
        return None


def sessionize(conn, *, gap: int = config.SESSION_GAP_SEC) -> dict:
    rows = conn.execute("SELECT id, datetime_original FROM media_items").fetchall()
    timed = []
    for mid, dt in rows:
        ep = _epoch(dt)
        if ep is not None:
            timed.append((ep, mid))
            conn.execute("UPDATE media_items SET dt_utc=? WHERE id=?", (ep, mid))
    timed.sort()
    conn.execute("UPDATE media_items SET session_id=NULL")  # clear FK refs BEFORE deleting sessions
    conn.execute("DELETE FROM sessions")
    n_sessions = 0
    if timed:
        sess_start = prev = timed[0][0]
        members: list[int] = []

        def flush(start, end, mem):
            nonlocal n_sessions
            if not mem:
                return
            cur = conn.execute(
                "INSERT INTO sessions (started_utc, ended_utc, media_count) VALUES (?,?,?)",
                (start, end, len(mem)),
            )
            sid = cur.lastrowid
            conn.executemany("UPDATE media_items SET session_id=? WHERE id=?", [(sid, m) for m in mem])
            n_sessions += 1

        for ep, mid in timed:
            if ep - prev > gap:
                flush(sess_start, prev, members)
                members, sess_start = [], ep
            members.append(mid)
            prev = ep
        flush(sess_start, prev, members)
    conn.commit()
    return {"sessions": n_sessions, "timed_media": len(timed)}
