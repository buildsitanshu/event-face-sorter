# Proxy eval for the accompaniment ("who came with you") candidates. There is NO ground truth for
# "who accompanied whom" until named people confirm in the UI, so this gate cannot measure precision
# directly. Instead it asserts the candidate lists are STRUCTURALLY trustworthy, the properties that,
# if violated, mean we're hallucinating bonds from crowd noise or a poisoned cluster:
#   E-FIXTURE : no candidate is a fixture/connector cluster (ubiquity / merged-identity guard).
#   E-WITNESS : >= 85% of candidates have an intimate-frame OR burst-coherent witness.
#   E-CROWD   : no candidate rests on crowd-only evidence, and median crowd-share <= 0.40.
# Honest-failure: on red it prints WHICH gate failed and the coverage/suppression/abstention numbers,
# so the success shape is "fewer, trustworthy candidates with high abstention", never a dense graph.
# `python -m convo_gallery.score_companions` exits 0 iff all gates pass.
from __future__ import annotations

import json
import statistics
import sys

from . import config
from .db import open_db

WITNESS_MIN = 0.85       # fraction of candidates with an intimate-or-burst witness
CROWD_SHARE_MAX = 0.40   # median allowed share of a candidate's shared photos that are crowd (n>5)


def evaluate(conn) -> dict:
    v: list[str] = []

    total = conn.execute("SELECT COUNT(*) FROM companion_candidates").fetchone()[0]
    if total == 0:
        return {"ok": False, "violations": ["no companion candidates, run the companions stage first"], "candidates": 0}

    # E-FIXTURE: a candidate must never be a guarded (fixture/connector) cluster
    bad_fixture = conn.execute(
        "SELECT COUNT(*) FROM companion_candidates cc JOIN cluster_flags cf ON cf.cluster_id=cc.cand_cluster "
        "WHERE cf.flag IN ('fixture','connector')"
    ).fetchone()[0]
    if bad_fixture:
        v.append(f"E-FIXTURE: {bad_fixture} candidates are fixture/connector clusters (ubiquity/merge poison)")

    # E-WITNESS: most candidates must be backed by an intimate frame or a time-burst
    with_witness = conn.execute(
        "SELECT COUNT(*) FROM companion_candidates WHERE intimate_photos > 0 OR burst_photos > 0"
    ).fetchone()[0]
    witness_frac = with_witness / total
    if witness_frac < WITNESS_MIN:
        v.append(f"E-WITNESS: only {witness_frac:.2f} of candidates have an intimate/burst witness (< {WITNESS_MIN})")

    # E-CROWD: none on crowd-only evidence, and the median crowd-share is bounded
    crowd_only = conn.execute("SELECT COUNT(*) FROM companion_candidates WHERE small_photos < 1").fetchone()[0]
    if crowd_only:
        v.append(f"E-CROWD: {crowd_only} candidates rest on crowd-only evidence (no <=5-person frame)")
    shares = [
        (co - sm) / co
        for co, sm in conn.execute("SELECT co_photos, small_photos FROM companion_candidates").fetchall()
        if co
    ]
    median_crowd = statistics.median(shares) if shares else 0.0
    if median_crowd > CROWD_SHARE_MAX:
        v.append(f"E-CROWD: median crowd-share {median_crowd:.2f} exceeds {CROWD_SHARE_MAX}")

    return {
        "ok": not v,
        "violations": v,
        "candidates": total,
        "witness_fraction": round(witness_frac, 3),
        "median_crowd_share": round(median_crowd, 3),
        "candidates_from_guarded_clusters": bad_fixture,
    }


def summary(conn) -> dict:
    grads = conn.execute("SELECT COUNT(*) FROM clusters WHERE is_unknown=0 AND face_count>0").fetchone()[0]
    served = conn.execute("SELECT COUNT(DISTINCT grad_cluster) FROM companion_candidates").fetchone()[0]
    by_bucket = {
        b: n for b, n in conn.execute(
            "SELECT bucket, COUNT(*) FROM companion_candidates GROUP BY bucket"
        ).fetchall()
    }
    confirmed = conn.execute("SELECT decision, COUNT(*) FROM companion_confirmations GROUP BY decision").fetchall()
    return {
        "graduates_total": grads,
        "graduates_with_candidates": served,
        "graduates_abstained": grads - served,  # honest: some named people legitimately have no companion
        "candidates_by_bucket": by_bucket,
        "fixtures": conn.execute("SELECT COUNT(*) FROM cluster_flags WHERE flag='fixture'").fetchone()[0],
        "connectors": conn.execute("SELECT COUNT(*) FROM cluster_flags WHERE flag='connector'").fetchone()[0],
        "co_presence_edges": conn.execute("SELECT COUNT(*) FROM co_presence_edges").fetchone()[0],
        "human_confirmations": {d: n for d, n in confirmed},
    }


def main(argv: list[str] | None = None) -> int:
    conn = open_db(config.DB_PATH)
    ev = evaluate(conn)
    print(json.dumps({"eval": ev, "summary": summary(conn)}, indent=2))
    return 0 if ev["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
