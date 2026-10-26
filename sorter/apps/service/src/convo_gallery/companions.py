# "Who came with you": accompaniment inference. Turns face co-occurrence into ranked companion
# SUGGESTIONS that a named person then CONFIRMS ("did you come with them?"). The confirmation is the
# ground truth; the inference only needs good candidates. Camera id was stripped from every file, so
# the working signal is intimate co-presence (a named person alone with 1-2 people IS with them), with
# time-bursts as the "same camera/moment" substitute. Everything runs inside the single antelopev2
# embedding space (the only space faces are clustered in), no cross-model comparison happens here.
#
# Pipeline (sequential, single writer: no races):
#   build_graph  -> cluster_flags (fixture/connector guards) + co_presence_edges (incl. unknown<->unknown)
#   rank_candidates -> companion_candidates (anchored on a named person, guarded, ranked, bucketed)
#   confirm / album_media -> the human-in-the-loop + the final personalised album.
from __future__ import annotations

import math
import time
from collections import defaultdict
from itertools import combinations

from .query.people import query_media_ids

# --- operating point (one block; the operator tunes these after the first spot-check) ---
FIXTURE_MAX = 40    # an UNKNOWN cluster in more than this many photos is a fixture (staff/over-merge), not a companion
GRAD_BREADTH = 3    # an UNKNOWN sharing an intimate frame with more than this many distinct named people is a connector
FACE_MIN = 70       # px; below this a face is a background stranger, not a posed subject -> down-weighted
EDGE_CAP = 20       # photos with more than this many distinct people are crowd shots -> skipped for edge-building (logged)
BURST_GAP = 10      # seconds; shared photos within this gap of another are one posing burst ("same moment")
MIN_COPHOTOS = 2    # never assert a companion from a single shared frame
GAMMA = 1.0         # weight on the intimate-frame anchor
BETA = 0.5          # weight on burst evidence (sqrt-capped)


def _clique_factor(n: int) -> float:
    """Crowd down-weight: a 2-person photo is full evidence; a 40-person auditorium shot ~0."""
    return 1.0 / max(1, n - 1)


def build_graph(conn) -> dict:
    """Stage 1+2: per-photo membership -> guard flags + symmetric co-presence edges (all cluster pairs,
    including unknown<->unknown = the full social graph). Returns build stats incl. the crowd-skip count
    (never a silent cap)."""
    # cluster identity (named person vs unknown) + its total photo spread
    is_unknown: dict[int, int] = {}
    media_count: dict[int, int] = {}
    for cid, u, mc in conn.execute("SELECT id, is_unknown, media_count FROM clusters").fetchall():
        is_unknown[cid] = u
        media_count[cid] = mc

    # every usable, clustered face (photos AND videos): which media, which cluster, how big, captured
    # when. A video contributes one (media, cluster) entry per person across its frames, so two people
    # appearing in the same clip count as co-present (videos feed the companion graph).
    rows = conn.execute(
        "SELECT f.media_id, f.cluster_id, f.face_px, m.dt_utc "
        "FROM faces f JOIN media_items m ON m.id=f.media_id "
        "WHERE f.is_usable=1 AND f.cluster_id IS NOT NULL AND m.kind IN ('raw','jpeg','video')"
    ).fetchall()

    # per-media: best (largest) face px per cluster, and capture time
    media_px: dict[int, dict[int, int]] = defaultdict(dict)
    media_dt: dict[int, int | None] = {}
    for mid, cid, px, dt in rows:
        cur = media_px[mid].get(cid)
        if cur is None or (px or 0) > cur:
            media_px[mid][cid] = px or 0
        media_dt[mid] = dt

    # accumulators keyed by unordered pair (a<b)
    co_photos: dict[tuple[int, int], int] = defaultdict(int)
    intimate: dict[tuple[int, int], int] = defaultdict(int)
    small: dict[tuple[int, int], int] = defaultdict(int)
    weight: dict[tuple[int, int], float] = defaultdict(float)
    pair_dts: dict[tuple[int, int], list[int]] = defaultdict(list)
    # connector evidence: which named people each unknown shares an intimate (<=5) frame with
    grad_breadth: dict[int, set[int]] = defaultdict(set)

    crowd_skipped = 0
    for mid, px_by_cluster in media_px.items():
        clusters = list(px_by_cluster)
        n = len(clusters)
        if n < 2:
            continue
        if n > EDGE_CAP:
            crowd_skipped += 1
            continue  # crowd shot: per-pair weight would be ~0; skip to bound work (reported, not silent)
        g = sum(1 for c in clusters if is_unknown.get(c) == 0)  # named people in this photo
        grad_split = 1.0 / max(1, g)
        cf = _clique_factor(n)
        dt = media_dt.get(mid)
        # connector evidence on small frames
        if n <= 5:
            grads_here = [c for c in clusters if is_unknown.get(c) == 0]
            unknowns_here = [c for c in clusters if is_unknown.get(c) == 1]
            for u in unknowns_here:
                for gg in grads_here:
                    grad_breadth[u].add(gg)
        for a, b in combinations(sorted(clusters), 2):
            fg = 1.0 if min(px_by_cluster[a], px_by_cluster[b]) >= FACE_MIN else 0.25
            key = (a, b)
            co_photos[key] += 1
            if n <= 2:
                intimate[key] += 1
            if n <= 5:
                small[key] += 1
            weight[key] += cf * grad_split * fg
            if dt is not None:
                pair_dts[key].append(dt)

    # burst: a shared photo time-adjacent (<= BURST_GAP) to another shared photo of the same pair
    def burst_count(dts: list[int]) -> int:
        if len(dts) < 2:
            return 0
        s = sorted(dts)
        n = 0
        for i, t in enumerate(s):
            prev_ok = i > 0 and (t - s[i - 1]) <= BURST_GAP
            next_ok = i < len(s) - 1 and (s[i + 1] - t) <= BURST_GAP
            if prev_ok or next_ok:
                n += 1
        return n

    now = int(time.time())
    # --- guard flags ---
    conn.execute("DELETE FROM cluster_flags")
    for cid in is_unknown:
        flag, reason = "ok", None
        if is_unknown.get(cid) == 1:
            breadth = len(grad_breadth.get(cid, ()))
            # A fixture is in many photos AND spread across many named people (staff / photographer /
            # over-merge). Someone in many photos but touching <= GRAD_BREADTH named people is NOT a
            # fixture: they are one named person's dedicated companion (a parent/partner/close friend who
            # appears in lots of THAT named person's photos), so they must stay eligible.
            if media_count.get(cid, 0) > FIXTURE_MAX and breadth > GRAD_BREADTH:
                flag, reason = "fixture", f"in {media_count[cid]} photos across {breadth} named people"
            elif breadth > GRAD_BREADTH:
                flag, reason = "connector", f"intimate with {breadth} distinct named people (> {GRAD_BREADTH})"
            conn.execute(
                "INSERT INTO cluster_flags (cluster_id, flag, reason, media_count, grad_breadth, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (cid, flag, reason, media_count.get(cid, 0), breadth, now),
            )

    # --- edges ---
    conn.execute("DELETE FROM co_presence_edges")
    edge_rows = []
    for key, cp in co_photos.items():
        a, b = key
        edge_rows.append((a, b, cp, intimate[key], small[key], burst_count(pair_dts.get(key, [])), round(weight[key], 6)))
    conn.executemany(
        "INSERT INTO co_presence_edges (a_cluster, b_cluster, co_photos, intimate_photos, small_photos, burst_photos, weight) "
        "VALUES (?,?,?,?,?,?,?)",
        edge_rows,
    )
    conn.commit()
    return {
        "edges": len(edge_rows),
        "crowd_photos_skipped": crowd_skipped,
        "edge_cap": EDGE_CAP,
        "fixtures": conn.execute("SELECT COUNT(*) FROM cluster_flags WHERE flag='fixture'").fetchone()[0],
        "connectors": conn.execute("SELECT COUNT(*) FROM cluster_flags WHERE flag='connector'").fetchone()[0],
    }


def _flag_of(conn) -> dict[int, str]:
    return {cid: fl for cid, fl in conn.execute("SELECT cluster_id, flag FROM cluster_flags").fetchall()}


def _bucket(score: float, intimate_photos: int) -> str:
    if intimate_photos >= 2 or score >= 3.0:
        return "high"
    if score >= 1.2:
        return "likely"
    return "maybe"


def rank_candidates(conn) -> dict:
    """Stage 3: ranked companion candidates, anchored on a named person, from the edges, with the hard guards:
    candidate is not a fixture/connector, shares >= MIN_COPHOTOS frames, and has >= 1 non-crowd witness.
    Candidates may be unknown groups OR other named people (a friend who is also named)."""
    flags = _flag_of(conn)
    is_unknown = {cid: u for cid, u in conn.execute("SELECT id, is_unknown FROM clusters").fetchall()}
    grads = [cid for cid, u in is_unknown.items() if u == 0]

    # gather every edge touching each named person (edges are stored a<b, so look both ways)
    per_grad: dict[int, list[dict]] = defaultdict(list)
    for a, b, cp, intimate_p, small_p, burst_p, w in conn.execute(
        "SELECT a_cluster, b_cluster, co_photos, intimate_photos, small_photos, burst_photos, weight FROM co_presence_edges"
    ).fetchall():
        for g, cand in ((a, b), (b, a)):
            if is_unknown.get(g) != 0:
                continue  # anchor must be a named person
            if cand == g:
                continue
            if flags.get(cand) in ("fixture", "connector"):
                continue  # ubiquity / merged-identity guard
            if cp < MIN_COPHOTOS:
                continue  # never from a single frame
            if small_p < 1:
                continue  # crowd-only evidence rejected
            score = w + GAMMA * intimate_p + BETA * math.sqrt(burst_p)
            per_grad[g].append({
                "cand": cand, "score": score, "co": cp, "intimate": intimate_p,
                "small": small_p, "burst": burst_p,
            })

    conn.execute("DELETE FROM companion_candidates")
    out_rows = []
    for g in grads:
        cands = sorted(per_grad.get(g, []), key=lambda d: (-d["score"], -d["co"], d["cand"]))
        for rank, d in enumerate(cands, start=1):
            out_rows.append((
                g, d["cand"], round(d["score"], 6), d["co"], d["intimate"], d["small"],
                d["burst"], _bucket(d["score"], d["intimate"]), rank,
            ))
    conn.executemany(
        "INSERT INTO companion_candidates "
        "(grad_cluster, cand_cluster, score, co_photos, intimate_photos, small_photos, burst_photos, bucket, rank) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        out_rows,
    )
    conn.commit()
    served = conn.execute("SELECT COUNT(DISTINCT grad_cluster) FROM companion_candidates").fetchone()[0]
    return {
        "candidate_edges": len(out_rows),
        "graduates_total": len(grads),
        "graduates_with_candidates": served,
        "graduates_with_none": len(grads) - served,
    }


def build_all(conn) -> dict:
    """Run the full inference pipeline (graph -> candidates)."""
    g = build_graph(conn)
    c = rank_candidates(conn)
    return {"graph": g, "candidates": c}


def confirm(conn, grad_cluster: int, cand_cluster: int, decision: str) -> dict:
    """The human ground-truth write: a named person confirms/denies a suggested companion."""
    if decision not in ("yes", "no"):
        raise ValueError(f"decision must be 'yes' or 'no', got {decision!r}")
    conn.execute(
        "INSERT INTO companion_confirmations (grad_cluster, cand_cluster, decision, decided_at) VALUES (?,?,?,?) "
        "ON CONFLICT(grad_cluster, cand_cluster) DO UPDATE SET decision=excluded.decision, decided_at=excluded.decided_at",
        (grad_cluster, cand_cluster, decision, int(time.time())),
    )
    conn.commit()
    return {"grad_cluster": grad_cluster, "cand_cluster": cand_cluster, "decision": decision}


def confirmed_companions(conn, grad_cluster: int) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT cand_cluster FROM companion_confirmations WHERE grad_cluster=? AND decision='yes'", (grad_cluster,)
    ).fetchall()]


def album_clusters(conn, grad_cluster: int) -> list[int]:
    """The clusters whose media make up a named person's final album: themselves + every confirmed companion."""
    return [grad_cluster] + confirmed_companions(conn, grad_cluster)


def album_media_ids(conn, grad_cluster: int) -> list[int]:
    """Every photo the named person OR any confirmed companion appears in (the personalised album).
    Reuses the load-bearing query_media_ids so the album set and any download set are identical."""
    return query_media_ids(conn, album_clusters(conn, grad_cluster), mode="any")
