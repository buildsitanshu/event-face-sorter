# Sort step: write one folder per person under data/sorted/, holding that person's originals
# (copied, hard-linked or symlinked) for local photos, or a drive-links.txt for Drive items.
# The output dir is rebuilt from scratch on every run, so it carries a marker file and we refuse
# to delete any directory that does not have it. Nothing under the source folders is modified.
from __future__ import annotations

import json
import os
import re
import shutil
import time
import unicodedata

from . import config
from .links import drive_download_url, drive_view_url

MARKER = ".event-face-sorter"
SETTINGS_FILE = "sort-settings.json"
MODES = ("copy", "hardlink", "symlink")

README = """Sorted photos
=============

Each folder here is one person, and holds every photo that person appears in.

- Folders with a real name come from the headshots you gave the tool.
- Folders called person-NNN are automatic groups of the same face. Rename a copy of them
  elsewhere once you know who they are.
- People seen in fewer than {min_photos} photos get no folder. They are listed in index.json
  under "singles".
- Photos where no usable face was found are listed in index.json under "no_faces".
- Drive items are not copied. Their links are in drive-links.txt inside the person's folder.

Running the sort again rebuilds this whole folder from scratch, so rename or move copies
elsewhere, not the files in here.
"""


def folder_name(label: str | None, cluster_id: int) -> str:
    if label:
        name = "".join(
            c
            for c in unicodedata.normalize("NFC", label)
            if c.isalnum() or unicodedata.category(c).startswith("M") or c in " ._-"
        )
        name = re.sub(r"\s+", " ", name).strip()[:80].strip()
        if name:
            return name
    return f"person-{cluster_id:03d}"


def _assert_safe(out_dir: str, source_dirs: set[str]) -> None:
    # Compare real paths, so a symlink or an alternate spelling cannot hide an overlap.
    out_dir = os.path.realpath(out_dir)
    for s in {os.path.realpath(d) for d in source_dirs}:
        try:
            common = os.path.commonpath([out_dir, s])
        except ValueError:  # different drives
            continue
        if common == s:
            raise ValueError(f"output folder {out_dir} is inside the photo folder {s}; pick another place")
        if common == out_dir:
            raise ValueError(f"photo folder {s} is inside the output folder {out_dir}; pick another place")
    if os.path.exists(out_dir) and not os.path.exists(os.path.join(out_dir, MARKER)):
        raise ValueError(f"refusing to clear {out_dir}: it was not created by this tool")


def export_sorted(
    conn, out_dir: str | None = None, *, min_photos: int = config.MIN_PHOTOS, mode: str = config.SORT_MODE
) -> dict:
    out_dir = os.path.abspath(out_dir or config.SORTED_DIR)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    local_dirs = {
        os.path.dirname(r[0])
        for r in conn.execute("SELECT local_path FROM media_items WHERE source='local' AND local_path IS NOT NULL")
    }
    source_dirs = set(local_dirs)
    if local_dirs:
        source_dirs.add(os.path.commonpath(list(local_dirs)))
    # the headshot folders are the user's originals too
    source_dirs |= {
        os.path.dirname(r[0])
        for r in conn.execute("SELECT DISTINCT local_path FROM reference_faces WHERE local_path IS NOT NULL")
    }
    _assert_safe(out_dir, source_dirs)

    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    now = int(time.time())
    with open(os.path.join(out_dir, MARKER), "w", encoding="utf-8") as fh:
        fh.write(str(now))

    people_rows = conn.execute(
        "SELECT id, label, is_unknown, media_count FROM clusters WHERE media_count >= ? "
        "ORDER BY media_count DESC, id",
        (min_photos,),
    ).fetchall()

    used: set[str] = set()
    people = []
    files_written = links_written = missing = 0
    for cid, label, _unk, _mc in people_rows:
        folder = folder_name(label, cid)
        if folder in used:
            folder = f"{folder}-{cid}"
        used.add(folder)
        fdir = os.path.join(out_dir, folder)
        os.makedirs(fdir)
        rows = conn.execute(
            "SELECT DISTINCT m.id, m.filename, m.source, m.local_path, m.drive_file_id, m.size_bytes, m.kind "
            "FROM faces f JOIN media_items m ON m.id=f.media_id "
            "WHERE f.cluster_id=? AND f.is_usable=1 ORDER BY m.id",
            (cid,),
        ).fetchall()
        names: list[str] = []
        link_lines: list[str] = []
        taken: set[str] = set()
        for mid, filename, source, local_path, drive_id, size, _kind in rows:
            if source == "local":
                if not local_path or not os.path.exists(local_path):
                    missing += 1
                    continue
                dest_name = filename if filename not in taken else f"{mid}_{filename}"
                taken.add(dest_name)
                dest = os.path.join(fdir, dest_name)
                if mode == "copy":
                    shutil.copy2(local_path, dest)
                elif mode == "hardlink":
                    try:
                        os.link(local_path, dest)
                    except OSError:
                        shutil.copy2(local_path, dest)
                else:
                    os.symlink(local_path, dest)
                names.append(dest_name)
                files_written += 1
            else:
                link_lines.append(f"{filename}\t{drive_view_url(drive_id)}\t{drive_download_url(drive_id, size or 0)}\n")
                links_written += 1
        if link_lines:
            with open(os.path.join(fdir, "drive-links.txt"), "a", encoding="utf-8") as fh:
                fh.writelines(link_lines)
        people.append({
            "folder": folder, "cluster_id": cid, "label": label or None, "named": bool(label),
            "photo_count": len(names) + len(link_lines), "files": names,
        })

    singles = [
        {"cluster_id": cid, "photo_count": mc}
        for cid, mc in conn.execute(
            "SELECT id, media_count FROM clusters WHERE media_count > 0 AND media_count < ? ORDER BY id",
            (min_photos,),
        )
    ]
    no_faces = [
        r[0]
        for r in conn.execute(
            "SELECT m.filename FROM media_items m WHERE m.status='processed' AND NOT EXISTS "
            "(SELECT 1 FROM faces f WHERE f.media_id=m.id AND f.is_usable=1) ORDER BY m.id"
        )
    ]
    unprocessed = conn.execute(
        "SELECT COUNT(*) FROM media_items WHERE status NOT IN ('processed','skipped')"
    ).fetchone()[0]

    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "generated_at": now, "min_photos": min_photos, "mode": mode, "people": people,
            "singles": singles, "no_faces": no_faces, "unprocessed": unprocessed,
        }, fh, indent=2)
    with open(os.path.join(out_dir, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(README.format(min_photos=min_photos))

    # remember the settings beside the output folder so a later ./sort.sh reuses them
    with open(os.path.join(os.path.dirname(out_dir), SETTINGS_FILE), "w", encoding="utf-8") as fh:
        json.dump({"min_photos": min_photos, "mode": mode, "written_at": now}, fh)

    return {
        "out_dir": out_dir, "people": len(people), "files_written": files_written,
        "links_written": links_written, "missing": missing, "singles": len(singles),
        "no_faces": len(no_faces), "mode": mode,
    }
