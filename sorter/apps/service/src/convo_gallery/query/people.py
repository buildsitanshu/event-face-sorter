# The load-bearing selection query: given a set of people (cluster ids), return the media items
# they appear in. The GUI's live count and the download builder BOTH call this, so the previewed
# set and the downloaded set are provably identical. Pure SQLite, no extra deps.
from __future__ import annotations

import sqlite3


def query_media_ids(
    conn: sqlite3.Connection,
    cluster_ids: list[int],
    *,
    mode: str = "any",
    session_id: int | None = None,
    dt_from: int | None = None,
    dt_to: int | None = None,
) -> list[int]:
    """Media ids where the chosen people appear.

    mode="any"  -> UNION: at least one chosen person appears (the default).
    mode="all"  -> INTERSECTION: every chosen person appears in the same item. Uses
                   COUNT(DISTINCT cluster_id) so two faces of ONE person can't fake a match.
    An empty selection returns [] (never "everything").
    """
    cluster_ids = list(dict.fromkeys(cluster_ids))  # de-dupe, preserve order
    if not cluster_ids:
        return []
    if mode not in ("any", "all"):
        raise ValueError(f"mode must be 'any' or 'all', got {mode!r}")

    placeholders = ",".join("?" for _ in cluster_ids)
    where = [f"f.cluster_id IN ({placeholders})", "f.is_usable = 1"]
    params: list = list(cluster_ids)
    if session_id is not None:
        where.append("m.session_id = ?")
        params.append(session_id)
    if dt_from is not None:
        where.append("m.dt_utc >= ?")
        params.append(dt_from)
    if dt_to is not None:
        where.append("m.dt_utc < ?")
        params.append(dt_to)
    where_sql = " AND ".join(where)

    if mode == "all":
        sql = (
            "SELECT f.media_id FROM faces f JOIN media_items m ON m.id = f.media_id "
            f"WHERE {where_sql} GROUP BY f.media_id HAVING COUNT(DISTINCT f.cluster_id) = ? "
            "ORDER BY f.media_id"
        )
        params.append(len(cluster_ids))
    else:
        sql = (
            "SELECT DISTINCT f.media_id FROM faces f JOIN media_items m ON m.id = f.media_id "
            f"WHERE {where_sql} ORDER BY f.media_id"
        )
    return [row[0] for row in conn.execute(sql, params).fetchall()]
