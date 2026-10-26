# CLI for the gallery pipeline:
#   event-face-sorter health
#   event-face-sorter scan     : recursively list the Drive folder into media_items (idempotent)
#   event-face-sorter summary  : print current DB counts by kind + status
from __future__ import annotations

import argparse
import json
import os

from . import config


def resolve_inputs(photos: str | None, people: str | None, media_id: str | None, roster_id: str | None, cfg=config) -> dict:
    """Pick the input mode. Local wins when a photos dir is given; roster is OPTIONAL in both modes.
    Returns {"mode": "local"|"drive", "media": <dir or folder id>, "roster": <dir|id|None>}.
    Raises SystemExit with a plain-language message when no media input exists."""
    photos = photos or cfg.MEDIA_DIR
    people = people or cfg.ROSTER_DIR
    media_id = media_id or cfg.ROOT_FOLDER_ID
    roster_id = roster_id or cfg.ROSTER_FOLDER_ID
    if photos:
        return {"mode": "local", "media": photos, "roster": people or None}
    if media_id:
        return {"mode": "drive", "media": media_id, "roster": roster_id or None}
    raise SystemExit(
        "run-all needs photos: pass --photos <folder> (local) or --media <driveFolderId> (Drive), "
        "or set CONVO_MEDIA_DIR / CONVO_ROOT_FOLDER_ID in .env. Headshots (--people / --roster) are optional."
    )


def require_roster_dir(inp: dict) -> None:
    """Fail before any work when a local headshots folder was named but does not exist."""
    if inp["mode"] == "local" and inp["roster"] and not os.path.isdir(inp["roster"]):
        raise SystemExit(f"headshots folder not found: {inp['roster']}. Check the --people path (or CONVO_ROSTER_DIR).")


def refuse_overlap(inp: dict, data_dir: str) -> None:
    """Exit before any write when the output folder and the photo or headshot folder contain each other."""
    if inp["mode"] != "local":
        return
    data = os.path.realpath(data_dir)
    msg = (
        "output folder {data} is inside the photo folder {real} (or the reverse): set CONVO_DATA_DIR to a "
        "folder outside your photos, for example CONVO_DATA_DIR=$HOME/event-face-sorter-data"
    )
    data_chain = _id_chain(data_dir)
    for src in (inp["media"], inp["roster"]):
        if not src:
            continue
        real = os.path.realpath(src)
        try:
            common = os.path.commonpath([data, real])
        except ValueError:  # different drives
            common = None
        if common in (data, real):
            raise SystemExit(msg.format(data=data, real=real))
        # (device, inode) pairs see through a case-different spelling on a case-insensitive filesystem
        src_chain = _id_chain(src)
        if _file_id(src) in data_chain or _file_id(data_dir) in src_chain:
            raise SystemExit(msg.format(data=data, real=real))


def _file_id(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def _id_chain(path: str) -> set[tuple[int, int]]:
    """(device, inode) of the path and of each ancestor up to the filesystem root; missing parts are skipped."""
    ids = set()
    cur = os.path.abspath(path)
    while True:
        fid = _file_id(cur)
        if fid is not None:
            ids.add(fid)
        parent = os.path.dirname(cur)
        if parent == cur:
            return ids
        cur = parent


def _has_run(db_path: str) -> bool:
    """True when the database exists and holds at least one media item. Never creates anything."""
    import pathlib
    import sqlite3

    if not os.path.exists(db_path):
        return False
    uri = pathlib.Path(db_path).resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        print(f"could not open {db_path}: {exc}")
        raise SystemExit(1) from exc
    try:
        return conn.execute("SELECT COUNT(*) FROM media_items").fetchone()[0] > 0
    except sqlite3.OperationalError:  # a database with no media_items table has no run in it
        return False
    finally:
        conn.close()


def resolve_sort_settings(min_photos: int | None, mode: str | None) -> tuple[int, str, str]:
    """Explicit flags win, then the settings the last sort stored, then the config defaults."""
    from .export_sorted import MODES, SETTINGS_FILE

    stored: dict = {}
    path = os.path.join(config.DATA_DIR, SETTINGS_FILE)
    if (min_photos is None or mode is None) and os.path.exists(path):  # both flags given: the file is overwritten, not read
        try:
            with open(path, encoding="utf-8") as fh:
                stored = json.load(fh)
            ok = isinstance(stored.get("min_photos"), int) and stored.get("mode") in MODES
        except (OSError, ValueError, AttributeError):
            ok = False
        if not ok:
            raise SystemExit(f"{path} is unreadable: delete it or pass --min-photos N and --mode M")
    if min_photos is not None or mode is not None:
        source = "flags"
    elif stored:
        source = SETTINGS_FILE
    else:
        source = "defaults"
    n = min_photos if min_photos is not None else stored.get("min_photos", config.MIN_PHOTOS)
    m = mode if mode is not None else stored.get("mode", config.SORT_MODE)
    return n, m, source


def _fmt_gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="event-face-sorter")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    s = sub.add_parser("scan")
    s.add_argument("--root", default=None, help="Drive folder id (defaults to config)")
    sub.add_parser("summary")
    pr = sub.add_parser("process")
    pr.add_argument("--kinds", default="photo", choices=["photo", "video", "all"])
    pr.add_argument("--workers", type=int, default=8)
    pr.add_argument("--batch", type=int, default=64)
    pr.add_argument("--limit", type=int, default=None)
    g = sub.add_parser("group")
    g.add_argument("--threshold", type=float, default=0.35)
    sub.add_parser("sessionize")
    e = sub.add_parser("export")
    e.add_argument("--include-unknown", action="store_true")
    rf = sub.add_parser("reference")
    rf.add_argument("--folder", default=None, help="Drive folder of reference headshots (default: CONVO_ROSTER_FOLDER_ID)")
    rf.add_argument("--enroll-size", type=int, default=1024)
    rf.add_argument("--dedupe-threshold", type=float, default=0.30)
    rf.add_argument("--match-threshold", type=float, default=0.40)
    rf.add_argument("--reenroll", action="store_true")
    rd = sub.add_parser("redetect")
    rd.add_argument("--workers", type=int, default=10)
    rd.add_argument("--batch", type=int, default=128)
    cl = sub.add_parser("classify", help="classify EVERY usable face: core named people by headshot + everyone else into unknown groups")
    cl.add_argument("--match-threshold", type=float, default=0.40, help="cosine-distance ceiling to claim a core (headshot) identity")
    cl.add_argument("--cluster-threshold", type=float, default=0.35, help="Chinese-Whispers distance for grouping the unknown remainder")
    ew = sub.add_parser("export-web", help="bake the gallery into a static JSON + thumbnail bundle (data/web)")
    ew.add_argument("--out", default=None, help="output dir (default data/web)")
    ew.add_argument("--thumb-px", type=int, default=512)
    so = sub.add_parser("sort", help="copy every original into data/sorted/<person>/ folders")
    so.add_argument("--min-photos", type=int, default=None, help="hide people seen in fewer photos (default: the last run's value)")
    so.add_argument("--mode", choices=["copy", "hardlink", "symlink"], default=None, help="copy | hardlink | symlink (default: the last run's value)")
    sub.add_parser("companions", help="build the accompaniment graph + per named person companion candidates")
    sub.add_parser("score-companions", help="proxy-eval the companion candidates (E-FIXTURE/E-WITNESS/E-CROWD), exit 0/1")
    sub.add_parser("calibrate")
    sc = sub.add_parser("score")
    sc.add_argument("--recall-ab", type=int, default=None, metavar="N", help="run the buffalo-vs-antelopev2 recall A/B on N photos")
    ra = sub.add_parser(
        "run-all",
        help="end-to-end from a local folder or two Drive folders: enroll roster -> scan -> process -> classify -> companions -> export-web",
    )
    ra.add_argument("--photos", default=None, metavar="DIR", help="local folder of photos + videos to sort")
    ra.add_argument("--people", default=None, metavar="DIR", help="optional local folder of headshots; filename = person's name")
    ra.add_argument("--media", default=None, help="Drive folder id of photos/videos (default: CONVO_ROOT_FOLDER_ID)")
    ra.add_argument("--roster", default=None, help="Drive folder id of headshots (default: CONVO_ROSTER_FOLDER_ID)")
    ra.add_argument("--limit", type=int, default=None, help="cap media processed per kind (use for a quick first run)")
    ra.add_argument("--workers", type=int, default=8)
    ra.add_argument("--min-photos", type=int, default=config.MIN_PHOTOS, help="hide people seen in fewer photos")
    ra.add_argument("--sort-mode", choices=["copy", "hardlink", "symlink"], default=config.SORT_MODE)
    ra.add_argument("--skip-video", action="store_true", help="photos only")
    args = p.parse_args(argv)

    if args.cmd == "health":
        from . import __version__

        print(json.dumps({"ok": True, "tool": "event-face-sorter", "version": __version__}))
        return

    from .db import open_db

    inp = None
    if args.cmd == "run-all":
        # refuse an overlapping output folder before anything is written
        inp = resolve_inputs(args.photos, args.people, args.media, args.roster)
        require_roster_dir(inp)
        refuse_overlap(inp, config.DATA_DIR)
    if args.cmd != "run-all" and (config.MEDIA_DIR or config.ROSTER_DIR):
        refuse_overlap({"mode": "local", "media": config.MEDIA_DIR, "roster": config.ROSTER_DIR or None}, config.DATA_DIR)
    if args.cmd == "sort":
        if not _has_run(config.DB_PATH):
            print(f"no run found in {config.DATA_DIR}: run ./run.sh --photos <folder> first")
            raise SystemExit(1)
        sort_min, sort_mode, sort_src = resolve_sort_settings(args.min_photos, args.mode)

    config.ensure_dirs()
    conn = open_db(config.DB_PATH)

    if args.cmd == "scan":
        from .drive import drive_service
        from .ingest import ingest

        root = args.root or config.ROOT_FOLDER_ID
        print(f"scanning Drive folder {root} ...")
        res = ingest(conn, drive_service(), root)
        total_bytes = sum(res["bytes_by_kind"].values())
        print(json.dumps(res, indent=2))
        print(f"TOTAL: {res['total']} files, {_fmt_gb(total_bytes)}")
        for k, b in sorted(res["bytes_by_kind"].items()):
            print(f"  {k:6} {res['by_kind'].get(k,0):>6} files  {_fmt_gb(b)}")

    elif args.cmd == "process":
        from .pipeline import run

        kinds = {"photo": ("raw", "jpeg"), "video": ("video",), "all": ("raw", "jpeg", "video")}[args.kinds]
        t0 = __import__("time").time()
        res = run(conn, kinds, workers=args.workers, batch=args.batch, limit=args.limit)
        res["seconds"] = round(__import__("time").time() - t0, 1)
        print(json.dumps(res, indent=2))

    elif args.cmd == "group":
        from .group_stage import group_all, sessionize

        print(json.dumps(group_all(conn, threshold=args.threshold), indent=2))
        print(json.dumps(sessionize(conn), indent=2))

    elif args.cmd == "sessionize":
        from .group_stage import sessionize

        print(json.dumps(sessionize(conn), indent=2))

    elif args.cmd == "export":
        from .export import export_gallery

        print(json.dumps(export_gallery(conn, include_unknown=args.include_unknown), indent=2))

    elif args.cmd == "reference":
        from .reference import dedupe, enroll, match_and_rebuild

        folder = args.folder or config.ROSTER_FOLDER_ID
        if not folder:
            raise SystemExit("reference needs a headshot folder: pass --folder <driveFolderId> or set CONVO_ROSTER_FOLDER_ID.")
        print("enroll:", json.dumps(enroll(conn, folder, size_px=args.enroll_size, force=args.reenroll)))
        print("dedupe:", json.dumps(dedupe(conn, threshold=args.dedupe_threshold)))
        print("match :", json.dumps(match_and_rebuild(conn, threshold=args.match_threshold), indent=2))

    elif args.cmd == "redetect":
        from .pipeline import redetect_photos

        t0 = __import__("time").time()
        res = redetect_photos(conn, workers=args.workers, batch=args.batch)
        res["seconds"] = round(__import__("time").time() - t0, 1)
        print(json.dumps(res, indent=2))

    elif args.cmd == "classify":
        from .reference import classify_all

        t0 = __import__("time").time()
        res = classify_all(conn, match_threshold=args.match_threshold, cluster_threshold=args.cluster_threshold)
        res["seconds"] = round(__import__("time").time() - t0, 1)
        print(json.dumps(res, indent=2))

    elif args.cmd == "export-web":
        from .export_web import export

        t0 = __import__("time").time()
        res = export(conn, args.out, thumb_px=args.thumb_px)
        res["seconds"] = round(__import__("time").time() - t0, 1)
        print(json.dumps(res, indent=2))

    elif args.cmd == "sort":
        from .export_sorted import export_sorted

        print(f"sort settings: min_photos={sort_min} mode={sort_mode} (from {sort_src})")
        print(json.dumps(export_sorted(conn, None, min_photos=sort_min, mode=sort_mode), indent=2))

    elif args.cmd == "companions":
        from .companions import build_all

        t0 = __import__("time").time()
        res = build_all(conn)
        res["seconds"] = round(__import__("time").time() - t0, 1)
        print(json.dumps(res, indent=2))

    elif args.cmd == "score-companions":
        from .score_companions import evaluate, summary

        ev = evaluate(conn)
        print(json.dumps({"eval": ev, "summary": summary(conn)}, indent=2))
        raise SystemExit(0 if ev["ok"] else 1)

    elif args.cmd == "calibrate":
        from .reference import calibrate

        print(json.dumps(calibrate(conn), indent=2))

    elif args.cmd == "score":
        from .score_roster import invariant, recall_ab, summary

        if args.recall_ab is not None:
            print(json.dumps(recall_ab(conn, sample=args.recall_ab), indent=2))
        else:
            inv = invariant(conn)
            print(json.dumps({"invariant": inv, "summary": summary(conn)}, indent=2))
            raise SystemExit(0 if inv["ok"] else 1)

    elif args.cmd == "run-all":
        import time

        from .companions import build_all
        from .export_sorted import export_sorted
        from .export_web import export as export_web
        from .pipeline import run as process_run
        from .reference import classify_all, dedupe

        print(f"mode={inp['mode']} media={inp['media']} roster={inp['roster']}")

        def step(label: str) -> None:
            print(f"\n=== {label} ===", flush=True)

        t0 = time.time()
        svc = None
        if inp["mode"] == "drive":
            from .drive import drive_service

            svc = drive_service()

        step("1/7  enroll headshots")
        if inp["roster"] is None:
            print("  no headshots given: faces will be grouped automatically (folders named person-NNN)")
        elif inp["mode"] == "local":
            from .local_source import enroll_local

            print("  enroll:", json.dumps(enroll_local(conn, inp["roster"])))
            print("  dedupe:", json.dumps(dedupe(conn)))
        else:
            from .reference import enroll

            print("  enroll:", json.dumps(enroll(conn, inp["roster"])))
            print("  dedupe:", json.dumps(dedupe(conn)))

        step("2/7  scan media folder")
        if inp["mode"] == "local":
            from .local_source import ingest_local

            res = ingest_local(conn, inp["media"])
        else:
            from .ingest import ingest

            res = ingest(conn, svc, inp["media"])
        print(f"  {res['total']} files: " + ", ".join(f"{k}={v}" for k, v in sorted(res["by_kind"].items())))

        batch = min(64, args.limit) if args.limit else 64  # honour --limit precisely on quick runs
        step("3/7  process photos (detect + embed every face)")
        print("  " + json.dumps(process_run(conn, ("raw", "jpeg"), workers=args.workers, batch=batch, limit=args.limit)))
        if not args.skip_video:
            step("3b/7 process videos (sample frames + detect)")
            print("  " + json.dumps(process_run(conn, ("video",), workers=args.workers, batch=batch, limit=args.limit)))

        step("4/7  classify (match roster if given + cluster everyone else)")
        cres = classify_all(conn)
        print(f"  mode={cres.get('mode')} " + json.dumps(cres))

        step("5/7  build the 'who came with you' companion graph")
        print("  " + json.dumps(build_all(conn)))

        step("6/7  export the static gallery (JSON + thumbnails)")
        ew = export_web(conn, None, min_photos=args.min_photos)
        print("  " + json.dumps(ew, indent=2))

        step("7/7  sort originals into per-person folders")
        sres = export_sorted(conn, None, min_photos=args.min_photos, mode=args.sort_mode)
        print("  " + json.dumps(sres))

        print(
            f"\nDONE in {round(time.time() - t0, 1)}s. Folders: {sres['out_dir']} ({sres['people']} people). "
            f"Gallery data: {ew['out_dir']}. View it with ./view.sh (http://127.0.0.1:3110/)."
        )

    elif args.cmd == "summary":
        rows = conn.execute(
            "SELECT kind, status, COUNT(*), COALESCE(SUM(size_bytes),0) FROM media_items GROUP BY kind, status ORDER BY kind, status"
        ).fetchall()
        for kind, status, n, b in rows:
            print(f"  {kind:6} {status:12} {n:>6} files  {_fmt_gb(b)}")
        tot = conn.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM media_items").fetchone()
        faces = conn.execute("SELECT COUNT(*), COALESCE(SUM(is_usable),0) FROM faces").fetchone()
        people = conn.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN is_unknown=0 THEN 1 ELSE 0 END),0) FROM clusters").fetchone()
        print(f"TOTAL media: {tot[0]} files, {_fmt_gb(tot[1])}")
        print(f"faces: {faces[0]} ({faces[1]} usable) | clusters: {people[0]} ({people[1]} multi-face people)")


if __name__ == "__main__":
    main()
