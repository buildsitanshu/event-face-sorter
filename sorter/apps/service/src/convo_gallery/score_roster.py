# Accuracy oracle for the face sorter. Two jobs:
#   1. invariant(): the HARD gate (fast, DB-only): the matching space is never mixed across models,
#      the photo redetect is complete, and the roster is enrolled at one model. A violation here is a
#      correctness bug (cross-space cosine distance), not a quality preference.
#   2. recall_ab(): the headline ACCURACY measurement: re-run BOTH detectors on the SAME preview
#      pixels and compare usable-faces-per-photo. This is the ground-truthed win of det_size 1600 +
#      antelopev2 (more real faces recovered), independent of any labels.
# `python -m convo_gallery.score_roster` runs the gate + a match/calibration summary and exits 0/1.
from __future__ import annotations

import json
import sys

import numpy as np

from . import config
from .db import open_db


def invariant(conn) -> dict:
    """The hard correctness gate. ok=False on any cross-model contamination."""
    from lia_face_recognition import config as fr_config

    current = fr_config.MODEL_TAG
    v: list[str] = []

    # (1) the roster is enrolled at exactly one model
    roster_tags = [r[0] for r in conn.execute(
        "SELECT embed_model_tag, COUNT(*) FROM reference_faces WHERE ref_person_id IS NOT NULL GROUP BY embed_model_tag"
    ).fetchall()]
    if len(roster_tags) > 1:
        v.append(f"roster mixes models: {roster_tags}")
    roster_tag = roster_tags[0] if roster_tags else None

    # (2) every clustered (matched) face is in the roster's model space
    if roster_tag is not None:
        bad = conn.execute(
            "SELECT COUNT(*) FROM faces WHERE cluster_id IS NOT NULL AND embed_model_tag != ?", (roster_tag,)
        ).fetchone()[0]
        if bad:
            v.append(f"{bad} matched faces are outside the roster model space {roster_tag}")

    # (3) the photo redetect is complete, no usable PHOTO face remains at an old model
    stale = conn.execute(
        "SELECT COUNT(*) FROM faces f JOIN media_items m ON m.id=f.media_id "
        "WHERE m.kind IN ('raw','jpeg') AND f.is_usable=1 AND f.embed_model_tag != ?", (current,)
    ).fetchone()[0]
    if stale:
        v.append(f"{stale} usable photo faces still at an old model (redetect incomplete)")

    # (4) no photo left unstamped (every photo with a preview was visited by redetect)
    unstamped = conn.execute(
        "SELECT COUNT(*) FROM media_items WHERE kind IN ('raw','jpeg') AND preview_path IS NOT NULL "
        "AND (detect_model_tag IS NULL OR detect_model_tag != ?)", (current,)
    ).fetchone()[0]
    if unstamped:
        v.append(f"{unstamped} photos not yet redetected at {current}")

    # (5) full-population classification: EVERY usable face in the matching space is grouped
    # (the core named people by headshot + everyone else into unknown friends/family clusters).
    # A usable in-space face with no cluster_id means classify_all left someone unclassified.
    if roster_tag is not None:
        unclassified = conn.execute(
            "SELECT COUNT(*) FROM faces WHERE is_usable=1 AND embed_model_tag=? AND cluster_id IS NULL",
            (roster_tag,),
        ).fetchone()[0]
        if unclassified:
            v.append(f"{unclassified} usable in-space faces are unclassified (classify-all incomplete)")

    return {"ok": not v, "current_model": current, "roster_model": roster_tag, "violations": v}


def summary(conn) -> dict:
    """Match outcome + best-distance histogram (the bimodal-valley diagnostic)."""
    from .reference import _best_sims, _ref_matrix, _roster_tag

    rp_of_row, R, _ = _ref_matrix(conn)
    if R.shape[0] == 0:
        return {"error": "no roster enrolled"}
    tag = _roster_tag(conn)
    fids, best_sim, _ = _best_sims(conn, R, rp_of_row, tag)
    dist = 1.0 - best_sim
    edges = [0.0, 0.2, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 1.01]
    hist = {f"{edges[i]:.2f}-{edges[i+1]:.2f}": int(((dist >= edges[i]) & (dist < edges[i + 1])).sum())
            for i in range(len(edges) - 1)}
    people = conn.execute("SELECT COUNT(*) FROM clusters WHERE media_count>0").fetchone()[0]
    matched = conn.execute("SELECT COUNT(*) FROM faces WHERE cluster_id IS NOT NULL").fetchone()[0]
    # classify_all breakdown: NAMED core people (is_unknown=0) vs UNKNOWN friends/family (is_unknown=1)
    core_people = conn.execute("SELECT COUNT(*) FROM clusters WHERE is_unknown=0 AND face_count>0").fetchone()[0]
    unknown_groups = conn.execute("SELECT COUNT(*) FROM clusters WHERE is_unknown=1").fetchone()[0]
    core_faces = conn.execute(
        "SELECT COALESCE(SUM(face_count),0) FROM clusters WHERE is_unknown=0"
    ).fetchone()[0]
    unknown_faces = conn.execute(
        "SELECT COALESCE(SUM(face_count),0) FROM clusters WHERE is_unknown=1"
    ).fetchone()[0]
    return {
        "roster_faces": int(R.shape[0]), "candid_faces_in_space": int(len(fids)),
        "faces_matched": int(matched), "match_rate": round(matched / max(1, len(fids)), 3),
        "people_with_photos": int(people), "best_distance_histogram": hist,
        "core_people_with_faces": int(core_people), "core_faces": int(core_faces),
        "unknown_groups": int(unknown_groups), "unknown_faces": int(unknown_faces),
    }


def recall_ab(conn, *, sample: int = 80, seed: int = 0) -> dict:
    """Run buffalo_l@640 and antelopev2@1600 on the SAME preview files; compare usable faces/photo.
    The ground-truthed detection-recall win (more real faces on identical pixels). Heavy: loads two
    models. Runs on a deterministic sample of photos that HAVE a saved preview."""
    import cv2
    from insightface.app import FaceAnalysis

    from lia_face_recognition.config import DEFAULT_GATE

    rows = conn.execute(
        "SELECT preview_path FROM media_items WHERE kind IN ('raw','jpeg') AND preview_path IS NOT NULL "
        "ORDER BY id"
    ).fetchall()
    paths = [r[0] for r in rows if r[0]]
    rng = np.random.default_rng(seed)
    if len(paths) > sample:
        idx = rng.choice(len(paths), size=sample, replace=False)
        paths = [paths[i] for i in sorted(idx)]

    def count_usable(app, path):
        img = cv2.imread(path)
        if img is None:
            return None
        n = 0
        for f in app.get(img):
            x1, y1, x2, y2 = (int(x) for x in f.bbox)
            face_px = min(x2 - x1, y2 - y1)
            if float(f.det_score) >= DEFAULT_GATE.min_det_score and face_px >= DEFAULT_GATE.min_face_px:
                n += 1
        return n

    def build(name, det):
        app = FaceAnalysis(name=name, providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_thresh=0.4, det_size=(det, det))
        return app

    old = build("buffalo_l", 640)
    new = build("antelopev2", 1600)
    old_tot = new_tot = used = 0
    gained = 0
    for p in paths:
        o = count_usable(old, p)
        n = count_usable(new, p)
        if o is None or n is None:
            continue
        used += 1
        old_tot += o
        new_tot += n
        gained += max(0, n - o)
    return {
        "sample_photos": used,
        "usable_faces_old_buffalo_640": old_tot,
        "usable_faces_new_antelopev2_1600": new_tot,
        "faces_per_photo_old": round(old_tot / max(1, used), 3),
        "faces_per_photo_new": round(new_tot / max(1, used), 3),
        "recall_gain_pct": round(100 * (new_tot - old_tot) / max(1, old_tot), 1),
        "net_faces_gained": new_tot - old_tot,
    }


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    conn = open_db(config.DB_PATH)
    if argv and argv[0] == "--recall-ab":
        n = int(argv[1]) if len(argv) > 1 else 80
        print(json.dumps(recall_ab(conn, sample=n), indent=2))
        return 0
    inv = invariant(conn)
    out = {"invariant": inv, "summary": summary(conn)}
    print(json.dumps(out, indent=2))
    return 0 if inv["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
