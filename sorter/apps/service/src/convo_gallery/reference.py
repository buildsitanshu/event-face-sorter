# Reference-roster matching: the supervised replacement for blind clustering. We enroll the known
# headshots, dedupe them into distinct people, then assign each candid face to the nearest reference
# person (within a cosine-distance threshold). Faces that match no roster member stay unassigned and
# are filtered out of the gallery. This turns hundreds of anonymous clusters into the handful of
# people you care about, and only the photos they are actually in.
from __future__ import annotations

import os
import time
from collections import defaultdict

import numpy as np

from . import config


def _blob(e) -> bytes:
    return np.asarray(e, dtype=np.float32).tobytes()


def _unblob(b) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def _roster_tag(conn) -> str:
    """The single embed_model_tag the roster is enrolled at. The roster DEFINES the matching space:
    candid faces are compared only within this same model, because cosine distance across model
    spaces (buffalo_l vs antelopev2) is meaningless. Raises if the roster mixes models, that would
    silently corrupt every match and must be fixed by a `reference --reenroll`."""
    tags = [r[0] for r in conn.execute(
        "SELECT DISTINCT embed_model_tag FROM reference_faces WHERE ref_person_id IS NOT NULL"
    ).fetchall()]
    if len(tags) > 1:
        raise ValueError(f"roster mixes embedding models {tags}; re-enroll the references at one model")
    return tags[0] if tags else ""


def enroll(conn, ref_folder_id: str, *, size_px: int = 1024, force: bool = False) -> dict:
    """Download each headshot's thumbnail, detect its primary (largest) face, store the embedding."""
    from lia_face_recognition.embed import detect_and_embed

    from .drive import download_thumbnail, drive_service, make_creds
    from .ingest import walk

    if force:
        conn.execute("DELETE FROM reference_faces")
        conn.commit()
    if conn.execute("SELECT COUNT(*) FROM reference_faces").fetchone()[0]:
        return {"enrolled": conn.execute("SELECT COUNT(*) FROM reference_faces").fetchone()[0], "skipped": True}

    from lia_face_recognition import config as fr_config

    creds = make_creds()
    svc = drive_service(creds)
    files = [f for f in walk(svc, ref_folder_id) if (f.get("mimeType") or "").startswith("image/")]
    enrolled = no_face = 0
    for f in files:
        fid = f["id"]
        path = os.path.join(config.PREVIEWS_DIR, f"ref_{fid}.jpg")
        if not download_thumbnail(svc, creds, fid, path, size_px=size_px):
            no_face += 1
            continue
        usable = [x for x in detect_and_embed(path) if x.is_usable]
        if not usable:
            no_face += 1
            continue
        primary = max(usable, key=lambda x: x.face_px)  # the headshot subject = the largest face
        conn.execute(
            "INSERT INTO reference_faces (drive_file_id, filename, embedding, embed_model_tag) VALUES (?,?,?,?)",
            (fid, f["name"], _blob(primary.embedding), fr_config.MODEL_TAG),
        )
        enrolled += 1
    conn.commit()
    return {"enrolled": enrolled, "no_face": no_face, "total_files": len(files), "model_tag": fr_config.MODEL_TAG}


def dedupe(conn, *, threshold: float = 0.30, seed: int = 0) -> dict:
    """Group headshots that are the same person (tight threshold) into ref_person_id."""
    from lia_face_recognition.chinese_whispers import chinese_whispers

    rows = conn.execute("SELECT id, embedding FROM reference_faces ORDER BY id").fetchall()
    if not rows:
        return {"reference_faces": 0, "distinct_people": 0}
    ids = [r[0] for r in rows]
    labels = chinese_whispers([_unblob(r[1]) for r in rows], threshold=threshold, seed=seed)
    for rid, lab in zip(ids, labels):
        conn.execute("UPDATE reference_faces SET ref_person_id=? WHERE id=?", (int(lab), rid))
    conn.commit()
    return {"reference_faces": len(ids), "distinct_people": len(set(labels))}


def _ref_people(conn):
    rows = conn.execute("SELECT ref_person_id, embedding, filename FROM reference_faces WHERE ref_person_id IS NOT NULL").fetchall()
    embs = defaultdict(list)
    names = defaultdict(list)
    for rp, emb, fn in rows:
        embs[rp].append(_unblob(emb))
        names[rp].append(fn)
    rp_ids = sorted(embs)
    cents = []
    labels = []
    for rp in rp_ids:
        m = np.mean(embs[rp], axis=0)
        cents.append(m / (np.linalg.norm(m) + 1e-9))
        labels.append(names[rp][0])  # name the person by their first headshot file
    return rp_ids, np.asarray(cents, dtype=np.float32), labels


def _ref_matrix(conn):
    """All reference embeddings (one row per headshot) + the ref_person each belongs to + a label
    per ref_person. Matching uses max-similarity over ALL of a person's headshots (more forgiving
    than a single centroid)."""
    rows = conn.execute(
        "SELECT ref_person_id, embedding, filename FROM reference_faces WHERE ref_person_id IS NOT NULL ORDER BY ref_person_id"
    ).fetchall()
    rp_of_row = [r[0] for r in rows]
    R = np.asarray([_unblob(r[1]) for r in rows], dtype=np.float32)
    labels: dict[int, str] = {}
    for rp, _, fn in rows:
        labels.setdefault(rp, fn)
    return rp_of_row, R, labels


def _best_sims(conn, R, rp_of_row, tag: str):
    """For every usable face IN THE ROSTER'S MODEL SPACE, the max similarity to ANY reference
    embedding + which ref_person. Faces at a different embed_model_tag (un-redetected photos,
    video frames) are excluded: comparing them to the roster would be a cross-space dot product."""
    faces = conn.execute(
        "SELECT id, embedding FROM faces WHERE is_usable=1 AND embed_model_tag=?", (tag,)
    ).fetchall()
    fids = [r[0] for r in faces]
    F = np.asarray([_unblob(r[1]) for r in faces], dtype=np.float32) if faces else np.zeros((0, 512), np.float32)
    best_sim = np.zeros(len(fids), dtype=np.float32)
    best_rp = np.full(len(fids), -1, dtype=np.int64)
    rp_arr = np.asarray(rp_of_row)
    block = 4096
    for s in range(0, len(fids), block):
        e = min(s + block, len(fids))
        sims = F[s:e] @ R.T  # (block, n_ref_embeddings)
        bi = sims.argmax(axis=1)
        best_sim[s:e] = sims[np.arange(e - s), bi]
        best_rp[s:e] = rp_arr[bi]
    return fids, best_sim, best_rp


def calibrate(conn) -> dict:
    """Print the best-match distance histogram so the operator can see the bimodal valley and pick
    a threshold (mated roster faces cluster near 0; strangers near 1)."""
    rp_of_row, R, _ = _ref_matrix(conn)
    if R.shape[0] == 0:
        return {"error": "no references"}
    _, best_sim, _ = _best_sims(conn, R, rp_of_row, _roster_tag(conn))
    dist = 1.0 - best_sim
    edges = [0.0, 0.2, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 1.01]
    hist = {}
    for i in range(len(edges) - 1):
        n = int(((dist >= edges[i]) & (dist < edges[i + 1])).sum())
        hist[f"{edges[i]:.2f}-{edges[i+1]:.2f}"] = n
    return {"faces": int(len(dist)), "best_distance_histogram": hist,
            "hint": "set the threshold at the valley between the near-0 (roster) and near-1 (stranger) modes"}


def match_and_rebuild(conn, *, threshold: float = 0.40) -> dict:
    """Assign every usable face to the roster person whose CLOSEST headshot is within `threshold`
    cosine distance. Rebuilds clusters (one per roster person); unmatched faces stay NULL (filtered)."""
    rp_of_row, R, labels = _ref_matrix(conn)
    if R.shape[0] == 0:
        return {"error": "no references enrolled/deduped"}
    tag = _roster_tag(conn)  # candids are matched only within the roster's model space
    sim_thr = 1.0 - threshold
    rp_ids = sorted(set(rp_of_row))

    conn.execute("UPDATE faces SET cluster_id=NULL")
    conn.execute("DELETE FROM clusters")
    now = int(time.time())
    rp_to_cluster = {}
    for rp in rp_ids:
        cur = conn.execute(
            "INSERT INTO clusters (label, rep_face_id, face_count, is_unknown, cluster_run_id, created_at) VALUES (?,?,0,0,2,?)",
            (labels[rp], None, now),
        )
        rp_to_cluster[rp] = cur.lastrowid

    fids, best_sim, best_rp = _best_sims(conn, R, rp_of_row, tag)
    best_rep: dict[int, tuple[int, float]] = {}
    assignments: list[tuple[int, int]] = []
    for i, fid in enumerate(fids):
        if best_sim[i] >= sim_thr:
            cl = rp_to_cluster[int(best_rp[i])]
            assignments.append((cl, fid))
            if cl not in best_rep or best_sim[i] > best_rep[cl][1]:
                best_rep[cl] = (fid, float(best_sim[i]))
    conn.executemany("UPDATE faces SET cluster_id=? WHERE id=?", assignments)
    conn.executemany("UPDATE clusters SET rep_face_id=? WHERE id=?", [(fid, cl) for cl, (fid, _) in best_rep.items()])
    conn.execute(
        "UPDATE clusters SET face_count=(SELECT COUNT(*) FROM faces WHERE faces.cluster_id=clusters.id), "
        "media_count=(SELECT COUNT(DISTINCT media_id) FROM faces WHERE faces.cluster_id=clusters.id)"
    )
    conn.commit()
    matched_people = conn.execute("SELECT COUNT(*) FROM clusters WHERE media_count>0").fetchone()[0]
    return {
        "reference_people": len(rp_ids),
        "people_with_photos": matched_people,
        "faces_total": len(fids),
        "faces_matched": len(assignments),
        "match_rate": round(len(assignments) / max(1, len(fids)), 3),
        "threshold": threshold,
    }


def classify_all(
    conn, *, match_threshold: float = 0.40, cluster_threshold: float = 0.35, seed: int = 0
) -> dict:
    """The roster (headshots) is OPTIONAL: with no enrolled references every usable face is grouped
    automatically (mode "unsupervised"); with a roster the two tiers below run (mode "roster").
    Full-population classification (the 'classify EVERY face' path, vs match_and_rebuild which
    keeps only the roster and discards the rest). Two tiers, both strictly within the roster's ONE
    model space (cross-space cosine is meaningless, so buffalo video faces are never grouped):
      tier 1: every usable face within `match_threshold` of a core roster person is assigned to
               that NAMED person (the people you gave headshots for);
      tier 2: the REMAINDER (no headshot match) is clustered among itself with Chinese-Whispers
               into UNKNOWN groups (is_unknown=1): the friends / partners / family.
    Nothing usable is dropped: every usable face in the matching space ends with a cluster_id, so
    score_roster's coverage clause reads 0 unclassified. Faces outside the space stay cluster_id
    NULL (un-redetected photos shouldn't exist post-redetect; buffalo video frames stay excluded)."""
    from lia_face_recognition.group import group_faces

    rp_of_row, R, labels = _ref_matrix(conn)
    if R.shape[0] == 0:
        # no roster: the headshots are optional, so group every usable face automatically
        from .group_stage import group_all

        res = group_all(conn, threshold=cluster_threshold, seed=seed)
        return {"mode": "unsupervised", **res}
    tag = _roster_tag(conn)  # the single model space; ALL grouping happens inside it

    # one fetch of every usable face IN THE SPACE, order is fixed so positions index F directly
    rows = conn.execute(
        "SELECT id, embedding FROM faces WHERE is_usable=1 AND embed_model_tag=? ORDER BY id", (tag,)
    ).fetchall()
    fids = [r[0] for r in rows]
    F = (
        np.asarray([_unblob(r[1]) for r in rows], dtype=np.float32)
        if rows
        else np.zeros((0, R.shape[1]), np.float32)
    )

    # best roster similarity per face (block matmul, same math as _best_sims)
    rp_arr = np.asarray(rp_of_row)
    best_sim = np.zeros(len(fids), dtype=np.float32)
    best_rp = np.full(len(fids), -1, dtype=np.int64)
    block = 4096
    for s in range(0, len(fids), block):
        e = min(s + block, len(fids))
        sims = F[s:e] @ R.T
        bi = sims.argmax(axis=1)
        best_sim[s:e] = sims[np.arange(e - s), bi]
        best_rp[s:e] = rp_arr[bi]
    sim_thr = 1.0 - match_threshold

    # fresh run: detach ALL faces (incl. stale video/photo assignments), drop old clusters
    conn.execute("UPDATE faces SET cluster_id=NULL")
    conn.execute("DELETE FROM clusters")
    now = int(time.time())
    run_id = 3  # classify_all run

    # --- tier 1: one NAMED cluster per core roster person ---
    rp_ids = sorted(set(rp_of_row))
    rp_to_cluster: dict[int, int] = {}
    for rp in rp_ids:
        cur = conn.execute(
            "INSERT INTO clusters (label, rep_face_id, face_count, is_unknown, cluster_run_id, created_at) "
            "VALUES (?,?,0,0,?,?)",
            (labels[rp], None, run_id, now),
        )
        rp_to_cluster[rp] = cur.lastrowid

    core_assign: list[tuple[int, int]] = []
    core_rep: dict[int, tuple[int, float]] = {}
    unmatched_pos: list[int] = []
    for i, fid in enumerate(fids):
        if best_sim[i] >= sim_thr:
            cl = rp_to_cluster[int(best_rp[i])]
            core_assign.append((cl, fid))
            if cl not in core_rep or best_sim[i] > core_rep[cl][1]:
                core_rep[cl] = (fid, float(best_sim[i]))
        else:
            unmatched_pos.append(i)
    conn.executemany("UPDATE faces SET cluster_id=? WHERE id=?", core_assign)
    conn.executemany("UPDATE clusters SET rep_face_id=? WHERE id=?", [(fid, cl) for cl, (fid, _) in core_rep.items()])

    # --- tier 2: cluster the residual into UNKNOWN groups (friends / family / partners) ---
    unknown_clusters = 0
    if unmatched_pos:
        embs = [F[i] for i in unmatched_pos]
        unmatched_fids = [fids[i] for i in unmatched_pos]
        res = group_faces(embs, threshold=cluster_threshold, seed=seed)
        glabels, greps = res["labels"], res["representatives"]
        lab_to_fids: dict[int, list[int]] = defaultdict(list)
        for fid, lab in zip(unmatched_fids, glabels):
            lab_to_fids[lab].append(fid)
        for lab, flist in lab_to_fids.items():
            rep_fid = unmatched_fids[greps[lab]]
            cur = conn.execute(
                "INSERT INTO clusters (label, rep_face_id, face_count, is_unknown, cluster_run_id, created_at) "
                "VALUES (NULL,?,0,1,?,?)",
                (rep_fid, run_id, now),
            )
            cid = cur.lastrowid
            conn.executemany("UPDATE faces SET cluster_id=? WHERE id=?", [(cid, fid) for fid in flist])
            unknown_clusters += 1

    conn.execute(
        "UPDATE clusters SET face_count=(SELECT COUNT(*) FROM faces WHERE faces.cluster_id=clusters.id), "
        "media_count=(SELECT COUNT(DISTINCT media_id) FROM faces WHERE faces.cluster_id=clusters.id)"
    )
    conn.commit()

    core_with_faces = conn.execute("SELECT COUNT(*) FROM clusters WHERE is_unknown=0 AND face_count>0").fetchone()[0]
    return {
        "mode": "roster",
        "model_space": tag,
        "core_people": len(rp_ids),
        "core_people_with_faces": core_with_faces,
        "core_faces_matched": len(core_assign),
        "unknown_clusters": unknown_clusters,
        "unknown_faces": len(unmatched_pos),
        "usable_faces_classified": len(fids),
        "match_threshold": match_threshold,
        "cluster_threshold": cluster_threshold,
    }
