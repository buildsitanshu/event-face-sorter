#!/usr/bin/env python
"""End-to-end smoke proof for the event face sorter. Run with the sorter venv:

    sorter/.venv/bin/python scripts/smoke.py [--work DIR] [--keep]

HONESTY NOTE: the fixture faces are cut from one group photo by the same detector that later
finds them, so this proves the WIRING, not recognition accuracy on real event photos. Asserted:
run A makes one folder per fixture face with the expected files (on disk and in index.json), the
no-face photo is listed under no_faces, notes.txt and .DS_Store never appear in the index, run B
names the folder Asha and holds the expected files, every copy under sorted/ is byte-identical
(sha256) to its source in photos/, and neither photos/ nor people/ changed across both runs.
Every summary line prints a measured value next to what was expected.

Exit 0 only when every assertion holds; exit 1 on a failed assertion; exit 2 on a bad fixture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_CWD = os.path.join(ROOT, "sorter")


class SmokeFail(Exception):
    def __init__(self, which: str, log: str | None = None):
        super().__init__(which)
        self.which = which
        self.log = log


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_fixture(work: str) -> dict:
    import cv2
    import numpy as np
    from insightface.data import get_image
    from lia_face_recognition.embed import detect_and_embed

    img = get_image("t1")
    usable = [f for f in detect_and_embed(img) if f.is_usable]
    n = len(usable)
    if n < 3:
        print(f"SMOKE FIXTURE: only {n} usable faces in the sample image, need at least 3")
        sys.exit(2)

    photos = os.path.join(work, "photos")
    people = os.path.join(work, "people")
    os.makedirs(photos)
    os.makedirs(people)
    cv2.imwrite(os.path.join(photos, "group.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])

    # One single-face photo per usable face: the group photo with every OTHER face painted over in
    # grey. (Tight crops, padded or upscaled, fell outside what the pipeline's fixed 1600 px
    # detector finds reliably; full-frame at native scale keeps the natural context it expects.)
    H, W = img.shape[:2]
    for i in range(len(usable)):
        single = img.copy()
        for j, other in enumerate(usable):
            if j == i:
                continue
            x1, y1, x2, y2 = (int(v) for v in other.bbox)
            mx, my = int((x2 - x1) * 0.3), int((y2 - y1) * 0.3)
            single[max(0, y1 - my):min(H, y2 + my), max(0, x1 - mx):min(W, x2 + mx)] = 128
        cv2.imwrite(os.path.join(photos, f"face_{i:02d}.jpg"), single, [cv2.IMWRITE_JPEG_QUALITY, 92])

    gx = np.tile(np.linspace(40, 200, 800, dtype=np.uint8), (600, 1))
    gy = np.tile(np.linspace(60, 160, 600, dtype=np.uint8).reshape(600, 1), (1, 800))
    gradient = np.dstack([gx, gy, ((gx.astype(int) + gy.astype(int)) // 2).astype(np.uint8)])
    cv2.imwrite(os.path.join(photos, "nobody.jpg"), gradient, [cv2.IMWRITE_JPEG_QUALITY, 92])
    with open(os.path.join(photos, "notes.txt"), "w") as fh:
        fh.write("not a photo\n")
    with open(os.path.join(photos, ".DS_Store"), "wb") as fh:
        fh.write(b"\x00\x00\x00\x01Bud1")

    video = False
    if shutil.which("ffmpeg"):
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", os.path.join(photos, "face_00.jpg"),
             "-t", "2", "-r", "5", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
             os.path.join(photos, "clip.mp4")],
            capture_output=True, text=True,
        )
        video = r.returncode == 0 and os.path.exists(os.path.join(photos, "clip.mp4"))
        if not video:
            print(f"warning: ffmpeg failed, skipping video: {r.stderr[-200:]}")
    else:
        print("warning: ffmpeg not found, skipping the video part (brew install ffmpeg)")

    shutil.copy2(os.path.join(photos, "face_00.jpg"), os.path.join(people, "Asha.jpg"))
    return {"photos": photos, "people": people, "n": n, "video": video}


def run_cli(work: str, label: str, data_dir: str, photos: str, people: str | None) -> tuple[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CONVO_")}
    env["CONVO_DATA_DIR"] = data_dir
    cmd = [sys.executable, "-m", "convo_gallery.cli", "run-all", "--photos", photos, "--workers", "2"]
    if people:
        cmd += ["--people", people]
    log_path = os.path.join(work, f"run{label}.log")
    with open(log_path, "w") as fh:
        rc = subprocess.run(cmd, cwd=SERVICE_CWD, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    log_tail = tail(log_path)
    if rc != 0:
        raise SmokeFail(f"run {label} exited {rc}", log_tail)
    return os.path.join(data_dir, "sorted"), log_tail


def tail(path: str, n: int = 30) -> str:
    with open(path, errors="replace") as fh:
        return "".join(fh.readlines()[-n:])


def main() -> int:
    ap = argparse.ArgumentParser(description="end-to-end smoke proof on a generated fixture")
    ap.add_argument("--work", default=None, help="work dir (default: a fresh temp dir)")
    ap.add_argument("--keep", action="store_true", help="keep the work dir on success")
    args = ap.parse_args()
    t0 = time.time()
    work = os.path.abspath(args.work) if args.work else tempfile.mkdtemp(prefix="efs-smoke-")
    os.makedirs(work, exist_ok=True)
    log_tail = None
    try:
        fx = build_fixture(work)
        n, photos, video = fx["n"], fx["photos"], fx["video"]
        people_dir = fx["people"]

        def hash_sources() -> dict:
            h = {f"photos/{f}": sha256(os.path.join(photos, f)) for f in sorted(os.listdir(photos))}
            h.update({f"people/{f}": sha256(os.path.join(people_dir, f)) for f in sorted(os.listdir(people_dir))})
            return h

        before = hash_sources()

        # Run A: no roster
        log_a = os.path.join(work, "runA.log")
        sorted_a, _ = run_cli(work, "A", os.path.join(work, "dataA"), photos, None)
        log_tail = tail(log_a)
        with open(os.path.join(sorted_a, "index.json")) as fh:
            idx_a = json.load(fh)
        if len(idx_a["people"]) != n:
            raise SmokeFail(f"run A: {len(idx_a['people'])} people, expected {n}", log_tail)
        face_names = {f"face_{i:02d}.jpg" for i in range(n)}
        seen_faces = set()
        for p in idx_a["people"]:
            files = set(p["files"])
            own = files & face_names
            if len(own) != 1:
                raise SmokeFail(f"run A: {p['folder']} holds {len(own)} face crops, expected 1: {sorted(files)}", log_tail)
            seen_faces |= own
            expect = {"group.jpg"} | own
            if video and "face_00.jpg" in own:
                expect.add("clip.mp4")
            if files != expect:
                raise SmokeFail(f"run A: {p['folder']} has {sorted(files)}, expected {sorted(expect)}", log_tail)
            on_disk = {x for x in os.listdir(os.path.join(sorted_a, p["folder"]))}
            if on_disk != files:
                raise SmokeFail(f"run A: {p['folder']} on disk {sorted(on_disk)} differs from index {sorted(files)}", log_tail)
        if seen_faces != face_names:
            raise SmokeFail("run A: not every face crop landed with exactly one person", log_tail)
        if idx_a["no_faces"] != ["nobody.jpg"]:
            raise SmokeFail(f"run A: no_faces is {idx_a['no_faces']}, expected ['nobody.jpg']", log_tail)
        blob = json.dumps(idx_a)
        if "notes.txt" in blob or ".DS_Store" in blob:
            raise SmokeFail("run A: notes.txt or .DS_Store leaked into index.json", log_tail)
        if hash_sources() != before:
            raise SmokeFail("run A: source photos or people folder changed", log_tail)

        # Run B: one-person roster
        log_b = os.path.join(work, "runB.log")
        sorted_b, _ = run_cli(work, "B", os.path.join(work, "dataB"), photos, fx["people"])
        log_tail = tail(log_b)
        with open(os.path.join(sorted_b, "index.json")) as fh:
            idx_b = json.load(fh)
        asha = [p for p in idx_b["people"] if p["folder"] == "Asha"]
        if not asha:
            raise SmokeFail("run B: no folder named Asha", log_tail)
        expect_b = {"face_00.jpg", "group.jpg"} | ({"clip.mp4"} if video else set())
        if set(asha[0]["files"]) != expect_b or set(os.listdir(os.path.join(sorted_b, "Asha"))) != expect_b:
            raise SmokeFail(f"run B: Asha holds {sorted(asha[0]['files'])}, expected {sorted(expect_b)}", log_tail)
        if not asha[0]["named"]:
            raise SmokeFail("run B: Asha entry is not named", log_tail)
        if len(idx_b["people"]) != n:
            raise SmokeFail(f"run B: {len(idx_b['people'])} people, expected {n}", log_tail)
        after = hash_sources()
        if after != before:
            raise SmokeFail("run B: source photos or people folder changed", log_tail)
        unchanged = sum(1 for k, v in before.items() if after.get(k) == v)

        # copy integrity: every file listed under a person is byte-identical to its source (names are unique)
        copies = identical = 0
        for sorted_dir, idx in ((sorted_a, idx_a), (sorted_b, idx_b)):
            for p in idx["people"]:
                for fname in p["files"]:
                    copy_path = os.path.join(sorted_dir, p["folder"], fname)
                    copies += 1
                    if sha256(copy_path) != before[f"photos/{fname}"]:
                        raise SmokeFail(f"copy {p['folder']}/{fname} differs from photos/{fname}", log_tail)
                    identical += 1

        print(f"faces detected: {n}")
        print(f"run A people: {len(idx_a['people'])} of {n} expected")
        print(f"run B named folder: Asha ({len(asha[0]['files'])} of {len(expect_b)} expected files)")
        print(f"no-face photos: {len(idx_a['no_faces'])} of 1 expected")
        print(f"sources unchanged: {unchanged} of {len(before)}")
        print(f"copies byte-identical: {identical} of {copies}")
        print(f"video: {'ran' if video else 'skipped'}")
        print(f"time: {round(time.time() - t0)}s")
    except SmokeFail as e:
        print(f"SMOKE FAIL: {e.which}")
        if e.log:
            print("--- last 30 lines of the run log ---")
            print(e.log)
        print(f"work dir kept: {work}")
        return 1
    if args.keep:
        print(f"work dir kept: {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
