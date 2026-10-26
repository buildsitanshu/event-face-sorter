# How event-face-sorter was built

This document is for a coding agent that has this repo open and needs to change it, debug it or rebuild part of it. `CLAUDE.md` tells you how to RUN the system for a user. This file tells you how it was BUILT, why each decision was taken, and where it is known to fall short. Every claim about code carries the path where you can check it. Read the limitations register (section 6) before you promise a user any result.

## 1. Where it came from

This tool was first built for a convocation, a graduation ceremony where the photographer's output of many thousands of photos had to reach each graduate as "the photos you are in". The photos sat in a shared Google Drive folder and every graduate had a registration headshot, so the first version pulled from Drive and matched faces against those headshots. It worked. A friend of the author then asked for the same thing for an event of their own, where there was no Drive folder and no headshots, only a folder of photos. So the private pieces were stripped out and the tool was generalised: a local folder goes in, one folder per person comes out, headshots are optional, and nothing is uploaded anywhere.

What changed:

- Input is a local folder (`sorter/apps/service/src/convo_gallery/local_source.py`). Google Drive is still wired but is a second path.
- The roster is optional. With no headshots, faces are grouped automatically (`sorter/apps/service/src/convo_gallery/reference.py`, function `classify_all`).
- Output is one folder per person on disk (`sorter/apps/service/src/convo_gallery/export_sorted.py`).
- The viewer is a static page with no dependencies (`sorter/apps/service/src/convo_gallery/viewer/`).
- The tree holds no private identifiers, and a test enforces it (`sorter/tests/test_public_tree.py`).

What was deleted because it depended on private infrastructure: the convocation-specific GUI (a Vite app), an upload-to-cloud step, and two MCP servers. The repo history is a single root commit, because the old history carried private identifiers.

Some names are historical. The Python module is `convo_gallery`, and some table and column names still say Drive (for example `media_items.drive_file_id` holds a local key in local mode, see `sorter/apps/service/src/convo_gallery/local_source.py`). Do not rename them without a migration.

## 2. Architecture

### 2.1 Three packages, one venv each

`setup.sh` creates a separate virtual environment in each of the three folders, installs each with its dev extras, then installs the two libraries into the sorter's venv as editable packages (`setup.sh`).

| Folder | Python package | Job |
|---|---|---|
| `face-recognition/` | `lia_face_recognition` | detect faces, embed them, cluster embeddings |
| `video-frame-reader/` | `lia_video_frame_reader` | sample frames from a video with ffmpeg |
| `sorter/` | `convo_gallery` | database, pipeline, CLI, export, API, viewer |

`setup.sh` also recreates a venv when `pip --version` fails inside it. That happens after the repo folder is moved, because a venv stores absolute paths. Without the check, setup would reuse a broken venv.

### 2.2 Face recognition library

- Model: InsightFace `antelopev2`, set by `MODEL_NAME` (env `FACE_MODEL`). It is a SCRFD detector plus an ArcFace network that outputs a 512-number vector per face (`face-recognition/src/lia_face_recognition/config.py`, `embed.py`).
- Runtime: CPU only through onnxruntime. The provider list is the single entry `CPUExecutionProvider`. The config comment says CoreML changes the numbers and would invalidate the baselines (`config.py`).
- Loading: `get_app()` builds one model per process, behind a lock, imported lazily so tests that never detect do not pay the import cost (`face-recognition/src/lia_face_recognition/detector.py`). If `antelopev2` fails to load, it falls back to `buffalo_l` and rewrites `MODEL_TAG` to `buffalo_l@cpu`.
- Download: the model is fetched by InsightFace's own `FaceAnalysis(name=...)` call on first use (`detector.py`). `CLAUDE.md` section 8 states the files land in `~/.insightface/models/antelopev2`. This repo has no download code of its own.
- Quality gate: a face is "usable" only if detector score >= 0.50, the smaller bbox side >= 30 px, and the variance of the Laplacian (a sharpness measure) >= 8.0. Faces below the bar are still stored with `is_usable = 0`, not dropped (`config.py`, `embed.py`).
- Tunables: `DET_SIZE` = 1600 x 1600, `DET_THRESH` = 0.4, `CLUSTER_THRESHOLD` = 0.35 (`config.py`).
- Clustering: Chinese Whispers, a graph method where every face starts as its own label and repeatedly adopts the label with the most edge weight among its neighbours. An edge exists when cosine similarity exceeds `1 - threshold`. It runs at most 30 iterations, uses a seeded random order and breaks ties on the smallest label, so the same input gives the same output. Edges are built in blocks of 512 rows so memory stays bounded (`face-recognition/src/lia_face_recognition/chinese_whispers.py`).
- Representative face per cluster: the medoid, the face closest to the cluster's mean (`face-recognition/src/lia_face_recognition/group.py`).

### 2.3 Video frame reader

One ffmpeg call writes JPEG frames using the filter `fps=<fps>` (default 1.0 in the library). Each frame gets timecode `index / fps`. An optional `max_frames` maps to `-frames:v` (`video-frame-reader/src/lia_video_frame_reader/frames.py`). `probe.py` wraps `ffprobe` for duration, size, codec and frame rate.

The sorter calls it with `fps = config.VIDEO_FPS`, default 0.5 (env `CONVO_VIDEO_FPS`), and passes no `max_frames` (`sorter/apps/service/src/convo_gallery/process.py`, `config.py`). So it samples one frame every 2 seconds across the whole clip.

### 2.4 The sorter: the seven steps

`./run.sh` runs `python -m convo_gallery.cli run-all`. The steps, in order, from `sorter/apps/service/src/convo_gallery/cli.py`:

1. Enroll headshots. Skipped with a message when no roster is given. Otherwise `enroll_local` then `dedupe`.
2. Scan the media folder: `ingest_local` lists files into `media_items`.
3. Process photos (detect and embed every face). Step "3b" processes videos unless `--skip-video`.
4. Classify: match the roster if given, and cluster everyone else.
5. Build the companion graph ("who came with you"), see `companions.py`.
6. Export the static gallery (JSON and thumbnails) to `data/web`.
7. Sort originals into per-person folders under `data/sorted`.

The final line starts `DONE in`.

Where each step lives:

- Database: SQLite in WAL mode with a 30 second busy timeout. Migrations are `*.sql` files applied once each and recorded in a `schema_migrations` table, so a non-repeatable statement such as `ALTER TABLE ADD COLUMN` is safe (`sorter/apps/service/src/convo_gallery/db.py`).
- Migration files (`sorter/apps/service/src/convo_gallery/migrations/`): `0001_init.sql` (media, faces, clusters, sessions), `0002_references.sql` (roster headshots), `0003_model_tags.sql` (model tag columns), `0004_companions.sql` (companion tables), `0005_local_source.sql`. Migration 0005 adds `media_items.source` (default `'drive'`), `media_items.local_path` and `reference_faces.local_path`.
- Local source (`local_source.py`): `walk_local` yields every file, skipping dot-folders and dot-files such as macOS `._` files. A file's key is `"local-"` plus the first 20 hex characters of the SHA-1 of its path relative to the photo folder. Insertion is `INSERT OR IGNORE` against a `UNIQUE` column, so scanning twice adds nothing.
- Accepted types (`sorter/apps/service/src/convo_gallery/ingest.py`, function `classify`):
  - images: jpg, jpeg, png, heic, heif, webp, tif, tiff
  - video: mp4, mov, avi, mts, m2ts, m4v, mkv, wmv, mpg, mpeg, 3gp
  - RAW (cr2, cr3, nef, arw, raf, dng, orf, rw2, pef, srw, raw): recorded with status `skipped` and error `local_raw_unsupported`
  - anything else: status `skipped`, error `not_media`
- Previews (`local_source.py`, `make_preview`): open with Pillow, apply the EXIF rotation (`ImageOps.exif_transpose`), convert to RGB, shrink to fit 2048 px on the long side, save JPEG at quality 90. HEIC opens only if `pillow_heif` imported; the import sits in a bare try/except, so a missing package fails silently until a HEIC file errors as `unreadable_image` (`process.py`).
- Detection (`sorter/apps/service/src/convo_gallery/process.py`): detection runs on the preview, not the original. Each face also gets a 160 px crop with 30 percent margin. Videos: sample frames, detect on each, then delete the temporary frame folder. A local source video is never deleted.
- Pipeline (`sorter/apps/service/src/convo_gallery/pipeline.py`): a `spawn` multiprocessing pool (default 8 workers) does the compute. Only the parent process writes to the database. It claims a batch (default 64) by setting `status='claimed'`, then writes each result as `processed` or `process_error`.
- Unsupervised grouping (`sorter/apps/service/src/convo_gallery/group_stage.py`, `group_all`): clusters every usable embedding at once with Chinese Whispers, drops old clusters and writes new ones. A cluster with exactly one face is flagged `is_unknown = 1`.
- Roster matching (`sorter/apps/service/src/convo_gallery/reference.py`):
  - `dedupe` merges headshots of one person at distance 0.30.
  - `classify_all` has two tiers. Tier 1 assigns every usable face whose closest headshot is within 0.40 cosine distance to that named person. Tier 2 clusters the remaining faces among themselves at 0.35 into unnamed groups.
  - The headshot's person name is its filename without extension (`local_source.py`, `enroll_local`). The largest usable face in a headshot is the one enrolled.
  - Matching only compares faces and headshots with the same `embed_model_tag`, because distances across two models mean nothing. `_roster_tag` raises if the roster mixes models.
  - `calibrate` prints a histogram of best-match distances with edges 0.0, 0.2, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 1.01.
- Sort export (`sorter/apps/service/src/convo_gallery/export_sorted.py`):
  - modes `copy`, `hardlink` (falls back to copy if linking fails), `symlink`
  - the whole output folder is deleted and rebuilt each time, so it carries a marker file `.event-face-sorter`; a folder without the marker is never cleared
  - writes `index.json`, `README.txt`, and `sort-settings.json` (one level above the sorted folder) so `./sort.sh` can reuse the settings
  - two guards stop it from touching the user's files: a realpath overlap check (`_assert_safe`) and the marker check
- Web export and viewer (`sorter/apps/service/src/convo_gallery/export_web.py`, `viewer/`): writes `index.json`, `people/<id>.json`, `companions/<id>.json`, 512 px thumbnails and face crops, then copies `index.html`, `app.js` and `tokens.css` next to them.
- API (`sorter/apps/service/src/convo_gallery/api.py`), FastAPI:
  - `GET /web/{path}` serves the bundle with a realpath containment check and returns 404 for anything outside it
  - `GET /original/{id}` serves a local original, inline or as attachment
  - `POST /api/people/{id}/label` renames a person (trimmed, cut to 80 characters, empty clears it)
  - `GET /zip/{id}` zips a person's originals; if some are missing from disk it adds `missing.txt` and sets the header `X-Missing-Count`
  - `GET /health`
  - also `/api/people`, `/api/people/{id}`, companions, album, query and manifest routes

### 2.5 Wrappers

- `run.sh`: loads `.env`, then `exec`s the CLI `run-all`.
- `view.sh`: probes the port first and exits 3 with `port N is in use` when busy, so the "Gallery:" line is never printed for a dead port. It starts uvicorn with `--host 127.0.0.1`.
- `sort.sh`: runs the CLI `sort`. It exits 1 with `no run found in ...` when the database has no media rows (`cli.py`, `_has_run`, which opens the database read-only and never creates it).
- `setup.sh`: described in 2.1.

### 2.6 Config and where data lives

`sorter/apps/service/src/convo_gallery/config.py` reads environment variables, and `.env.example` documents them. Defaults: `MIN_PHOTOS` = 2, `SORT_MODE` = `copy`, `VIDEO_FPS` = 0.5, `SESSION_GAP_SEC` = 5400 (90 minutes), `OAUTH_PATH` = `~/.config/event-face-sorter/oauth.json`.

Everything the tool writes lives under `DATA_DIR`, which is `CONVO_DATA_DIR` or `sorter/data/` by default: `gallery.db`, `previews/`, `crops/`, `frames/`, `originals/`, `sorted/`, `web/`, `sort-settings.json`.

### 2.7 Google Drive mode

Wired through `drive.py`, `ingest.py` (the Drive walker) and `scripts/drive_auth.py`. It reads with `drive.readonly` scope, detects on Drive's server-side thumbnail at 2048 px, and downloads originals only for videos. It was NOT exercised against a live Google account in this repo's current form (`README.md` section 6 says the same). Treat it as untested code.

## 3. The decisions and their reasons

Decision: the user's photo folder is read-only to the tool, and every output goes under `sorter/data` or `CONVO_DATA_DIR`.
Reason: the originals are irreplaceable and the tool deletes and rebuilds its own output. `refuse_overlap` in `sorter/apps/service/src/convo_gallery/cli.py` runs before any write and exits if the output folder is inside the photo or headshot folder, or the reverse. It compares real paths and also (device, inode) pairs, so a different spelling on a case-insensitive disk cannot hide an overlap. `export_sorted.py` repeats the check at write time.

Decision: detect on a 2048 px preview, not the full-size original.
Reason: speed, and one predictable image scale for the detector. `DET_SIZE` is set to 1600 so that a 2048 px preview is searched at close to full size (`local_source.py`, `config.py`). The code does not record a speed measurement against full-size originals.

Decision: `DET_SIZE` is 1600, not 640.
Reason: the comment in `face-recognition/src/lia_face_recognition/config.py` says 640 shrank the 2048 px previews by 3.2 times, so over half the faces fell under 60 px and 31 percent (under 40 px) were dropped. 1600 runs detection at about full preview size. Detector threshold was lowered from 0.5 to 0.4 and the minimum face size from 40 to 30 px for the same reason.

Decision: Chinese Whispers at cosine distance 0.35, roster match at 0.40.
Reason: 0.35 is described in the config comment as the usual literature value, and the gallery swept 0.30, 0.35 and 0.40 and froze one. The match threshold (0.40) is looser than the clustering threshold (0.35); the code gives no reason for the gap. These values were fixed on the original event's data and were not re-tuned on other event photos. Nothing in this repo measures their accuracy on new data.

Decision: the roster is optional; with none, group every face automatically.
Reason: most users do not have one clear photo per person. Unnamed folders are called `person-NNN` and can be renamed later (`reference.py`, `export_sorted.py`, function `folder_name`).

Decision: `MIN_PHOTOS` defaults to 2, so people seen in only one photo get no folder.
Reason: one-photo "people" are mostly passers-by and detector noise. They are not lost: they are listed under `singles` in `index.json` (`export_sorted.py`).

Decision: `copy` is the default sort mode, with `hardlink` and `symlink` as options.
Reason: a copy survives the user moving or deleting the originals and works across disks. Hardlink saves disk but only on the same drive, and falls back to copy if linking fails (`export_sorted.py`).

Decision: the viewer has no build step and no external resources.
Reason: it works offline and needs no toolchain. It is three static files (`viewer/index.html`, `viewer/app.js`, `viewer/tokens.css`). Routing uses the URL hash (`#/person/<id>`) in `app.js`. `tokens.css` holds the only raw colours; the page uses semantic names such as `--color-bg`, `--color-surface`, `--color-text`, `--space-*`, `--fs-*`, `--radius-*`. `sorter/tests/test_viewer_laws.py` bans motion (`transition`, `animation`, `@keyframes`) and checks the other viewer rules.

Decision: the API binds to 127.0.0.1 only.
Reason: it serves the user's private photos with no login. `view.sh` passes `--host 127.0.0.1`, and the "Gallery" line prints the same address. Do not change the host without adding authentication.

Decision: `scripts/check.sh` counts passed tests against a floor per suite instead of trusting the exit code.
Reason: a suite that collects zero tests, or skips all of them, exits 0. The script reads the count only from the final pytest summary line, strips colour codes, and fails closed (`FLOOR FAIL: ... count unreadable`) when it finds no number or more than one.

Decision: the private-string scan stores SHA-256 digests, not the strings.
Reason: the banned strings must not appear in the repo in any form, including inside the test that bans them (`sorter/tests/test_public_tree.py`).

Decision: public repo with a single root commit.
Reason: the earlier history carried private identifiers.

## 4. How it is tested and what the tests prove

### 4.1 Three suites with floors

`scripts/check.sh` first runs the public-tree scan (section 4.3) as its own step, then runs pytest inside each suite's own venv and enforces a minimum count of passed tests:

| Suite | Floor |
|---|---|
| `face-recognition` | 4 |
| `video-frame-reader` | 2 |
| `sorter` | 160 |

The real count is printed on each `floor ok:` line and exceeds the floor as tests are added. A suite whose final summary line names a skipped, deselected or xfail test, or does not say `passed`, fails (`FLOOR FAIL: <suite> has skipped or deselected tests`), whatever its count. Raise a floor when you add tests; never lower it. `--smoke` runs the end-to-end proof after the suites pass, and is skipped when any suite failed.

### 4.2 The smoke test

`scripts/smoke.py` builds a fixture and runs the real CLI twice. Fixture (`build_fixture`):

- the source image is InsightFace's bundled sample `t1` (`insightface.data.get_image`)
- it detects usable faces in it and needs at least 3, else exits 2; `README.md` section 7 reports 6 faces and 8 photos
- `group.jpg` is the whole sample image
- one `face_NN.jpg` per usable face: the same image with every other face painted grey (value 128, with a 30 percent margin), so each photo holds one findable face at native scale. The script's comment says tight crops fell outside what the 1600 px detector finds reliably
- `nobody.jpg`: a colour gradient with no face
- junk the scan must ignore: `notes.txt` and `.DS_Store`
- `clip.mp4`: a 2 second, 5 fps video looped from `face_00.jpg`, made with ffmpeg when ffmpeg exists
- `people/Asha.jpg`: a copy of `face_00.jpg`, the roster photo

Run A has no roster. It asserts one folder per usable face, each holding its own face photo plus `group.jpg` (plus the clip for `face_00`), `nobody.jpg` under `no_faces`, and that the junk files never reach `index.json`. Run B adds the one-person roster and asserts a named folder `Asha` with the expected files. Throughout it takes a SHA-256 of every source file before and after and fails if any changed, and checks that every copied file is byte-identical to its source. Exit 0 means all of that held; 1 is a failed assertion; 2 is a bad fixture.

What it proves: the wiring from folder to sorted folders, copy integrity, and that sources are untouched, plus a video frame path and a roster path.

What it does NOT prove: recognition accuracy on real event photos. The faces are cut from one image by the same detector that later finds them, so the test cannot fail on a recognition error. The script's own docstring says so. `README.md` reports a runtime of 10 to 25 seconds on an Apple M-series Mac.

### 4.3 The public-tree scan

`sorter/tests/test_public_tree.py` scans every tracked file. With a `.git` folder it uses `git ls-files` plus untracked files that are not ignored, so a file about to be added is scanned too; a listed file missing on disk is a failure. Without a `.git` folder (a ZIP download) it walks the tree, skipping `.venv`, `node_modules`, `__pycache__`, `*.egg-info` and similar folders at every level, a folder named `data` only at `sorter/data`, and files named `.DS_Store` or `.env`. Those are generated by `setup.sh`, by macOS or by local settings and are gitignored, so git mode never lists them. The test has no skip path. `scripts/check.sh` runs it as a separate step before the suites (`privacy scan: ok` or `PRIVACY SCAN FAIL`; a final line naming a skipped, deselected or xfail test is a `PRIVACY SCAN FAIL` too), and the sorter suite runs it again.

- Normalisation: before the digest and word checks the text goes through NFKC (full-width lookalikes become ASCII), loses soft hyphens and zero-width characters, has no-break spaces made plain spaces, is URL-decoded and lowercased.
- Digest check: for each stored digest it hashes every window of that length and compares. It runs four times: on the normalised text, on the raw text only lowercased (normalising can eat a token: URL-decoding swallows the first two letters of a token written after a percent sign, and NFKC merges a last letter with a combining accent that follows it), on the normalised text with all whitespace removed (a word split by a line wrap), and with each whitespace run collapsed to one space (a two-word token split across lines). So the banned strings are not in the repo, yet a match is found anywhere, even inside a longer word.
- Word digests: a second table holds digests of whole words; every run of letters and digits in the normalised text is hashed and compared, so a short word is caught as a word without matching inside longer words.
- Binary ban: a file holding a NUL byte or failing UTF-8 decoding is a failure, never a skip. A file whose extension is an image, RAW, video, database, pickle, model weight, archive or PDF type is a failure whatever its content.
- Generic patterns: a user home path, private network address shapes, Tailscale-style and mDNS-style private host names, Google API key, token and private-key shapes, Drive-id shapes (a run holding `1` plus 27 to 40 id characters that mixes upper case, lower case and a digit; a whole word of `1` plus 27 to 40 id characters, whatever its mix; and legacy ids starting `0B`), any email address outside `LICENSE`, the `authors` lines of `pyproject.toml` and the example, Anthropic and GitHub noreply domains, a personal mail domain, Indian mobile number shapes (`+91` forms, and a ten-digit number starting 6 to 9 that stands alone, so a digit run inside a hex digest does not count), em dashes and emoji.
- Unit tests in the same file plant fake tokens built at runtime and prove each rule fires, plus a clean paragraph that must produce no hit.
- Limits: HTML entities and base64 encodings are not decoded. File and folder names are not scanned, only file contents (a name is read only for the banned-extension check). Walk mode does not read the skipped folders and files above, so a token placed only there is not caught without `.git`. A token typed in a different script is not caught. The scan reads the working tree, so a change committed and then reverted before the scan is not seen in history; push a single squashed commit. It guards against accidents, not an adversary.

Any new file you add, including docs, is scanned. A long unbroken token holding the digit 1 and mixed-case letters, or any whole word of 28 to 41 id characters starting with 1, can trip a Drive-id pattern, and a standalone run of ten digits starting 6 to 9 trips the mobile pattern.

## 5. What a second run does

Read this before telling a user "re-running is safe". It is safe for the originals. It is not a clean incremental update.

Running `./run.sh` twice on the same folder with the same data folder:

- Step 2 rescans the folder but inserts only files whose path-based key is new (`INSERT OR IGNORE`). A renamed or moved file counts as a new file. A file edited in place under the same path is not re-processed.
- Step 3 selects only rows with `status='listed'` (`pipeline.py`). Finished files are skipped, so detection is not repeated.
- Before selecting, `run` returns any rows left as `claimed` by an interrupted run (crash, power loss, Ctrl-C) to `listed` (`reclaim_unfinished` in `pipeline.py`), so the next run picks them up and prints `resumed N file(s)`. Rows in `process_error` are not retried: `run-all` never selects them, and the only other path, `redetect` (`cli.py`, line 265), selects by `detect_model_tag` and preview, not by status, so it does not retry them either. Fix the cause and reset those rows by hand, or start a fresh data folder.
- Step 1 enrolls headshots only if the `reference_faces` table is empty (`enroll_local`). A changed headshot folder is ignored on a later run, and `run-all` has no flag to force re-enrollment.
- Step 4 deletes every cluster and rebuilds them (`classify_all`, `group_all`). Names a user typed in the gallery are stored on the cluster rows, so they are lost, and cluster ids change.
- Steps 6 and 7 rewrite the web bundle and delete and rebuild `sorted/`.

Renaming: `POST /api/people/{id}/label` updates only that cluster's `label`. `./sort.sh` then rebuilds the folders from the database without detecting again. If two different clusters get the same name, they do NOT merge. In `export_sorted.py`, the second folder with an already-used name is created as `<name>-<cluster_id>`. There is no merge or split feature anywhere in the API or the viewer.

## 6. Limitations register

| Limitation | Where it shows | What to do about it |
|---|---|---|
| Recognition accuracy on real event photos has never been measured here. The thresholds come from another event. | Wrong or mixed people in folders. | Run `./run.sh --photos <dir> --limit 20` first and have the user judge the folders. That trial is the first real signal. |
| Small, turned-away, blurred, masked or dim faces are missed or merged. Group photos with many small faces lose the smallest ones. | Photo under `no_faces` in `index.json`, or a person missing from a photo. | Faces under 30 px, detector score under 0.50 or sharpness under 8.0 are stored as not usable (`config.py`). Lower the gate only with evidence. `FACE_DET_SIZE` and `FACE_DET_THRESH` are env overrides. |
| One person split across two folders (threshold too strict), or two people merged (too loose). | Duplicate `person-NNN` folders, or a folder with two people. | Give a headshot with `--people`. Or tune: `classify --cluster-threshold` (default 0.35) and `--match-threshold` (default 0.40), run from the `sorter/` folder after a run. Renaming alone does not merge folders (section 5). |
| RAW files are skipped in local mode. | `skipped` rows with `local_raw_unsupported`. | Use the JPEG siblings or convert. Supporting RAW needs a decoder in `make_preview`. |
| HEIC works only if `pillow-heif` imported. | `unreadable_image` errors on HEIC files. | Re-run `./setup.sh`, or convert to JPEG. |
| Video sampling is every 2 seconds by default (`CONVO_VIDEO_FPS` = 0.5), over the whole clip. A person visible for less than one interval can be missed. | A person absent from a clip they are in. | Raise `CONVO_VIDEO_FPS`; run time grows with it. |
| CPU only. The smoke test takes 10 to 25 seconds on a fixture of 8 photos and one clip (`README.md`). A real event of thousands of photos takes much longer. This repo records no throughput for real photos. | Long runs. | Estimate from the `--limit 20` timing (`CLAUDE.md` section 3). `--workers 2` helps when memory is short, because each worker loads its own model (`CLAUDE.md` section 6). |
| The model download is about 350 MB zipped and about 410 MB unpacked, cached in `~/.insightface` (`README.md` section 1). | First run needs network and disk. | Check free disk first. |
| Drive mode was never exercised against a live Google account in this form. | Any Drive run. | Treat as untested; test with a small folder first. |
| Windows is untested. The wrappers are bash. | Setup on Windows. | Use WSL2. |
| Historical names: module `convo_gallery`, Drive-named columns, a `students` table in `0001_init.sql`. | Confusing reads of the schema. | Leave them; renames need migrations and touch every query. |
| Re-run is not incremental (section 5): clusters and typed names are rebuilt, headshots are not re-enrolled, moved files are new files. | Lost names after a second `run.sh`. | Rename after the last `run.sh`, then use `./sort.sh`. Keep the data folder only if you accept a rebuild. |
| Interrupted runs: `claimed` rows are returned to `listed` at the start of `run` (`reclaim_unfinished`, `pipeline.py`). | The run prints `resumed N file(s)`. | Run the same command again. Rows in `process_error` are still not retried (see below). |
| No merge or split UI. Two groups given one name stay two folders. | Folders named `Name` and `Name-<id>`. | Merge outside the tool, or give headshots so one person matches one cluster. |
| `process_error` files are not retried. | `errors=E` in the progress line. | Fix the cause, then reset those rows' status by hand or start a fresh data folder. A video that failed because ffmpeg was missing stays `process_error` after ffmpeg is installed; delete the data folder and run again. |
| Folder names drop punctuation and keep letters, digits and combining marks in any script (`folder_name`, `export_sorted.py`); two names that reduce to the same string get a `-<cluster id>` suffix. | `Priya (bride)` becomes `Priya bride`. | Rename in the gallery, or accept the suffix. |

## 7. If you need to change X, start at Y

| Change | Start at |
|---|---|
| Thresholds: detector size, score, quality gate, clustering | `face-recognition/src/lia_face_recognition/config.py`; clustering call sites in `sorter/apps/service/src/convo_gallery/reference.py` (`classify_all`) and `group_stage.py` |
| Roster match threshold and headshot dedupe | `reference.py` (`classify_all`, `dedupe`); CLI flags in `cli.py` |
| Accepted file types | `sorter/apps/service/src/convo_gallery/ingest.py` (`RAW_EXT`, `JPEG_EXT`, `VIDEO_EXT`); local handling in `local_source.py` (`ingest_local`) |
| Preview size or format | `local_source.py` (`make_preview`) |
| Video sampling rate or rule | `video-frame-reader/src/lia_video_frame_reader/frames.py`; the rate is `VIDEO_FPS` in `sorter/apps/service/src/convo_gallery/config.py`; the call is in `process.py` (`process_video`) |
| Sort modes, folder naming, `index.json` shape | `export_sorted.py` (`MODES`, `folder_name`, `export_sorted`) |
| Viewer look and behaviour | `sorter/apps/service/src/convo_gallery/viewer/`; the bundle shape comes from `export_web.py`; rules in `sorter/tests/test_viewer_laws.py` |
| API routes | `sorter/apps/service/src/convo_gallery/api.py`; the bind address is in `view.sh` |
| Database schema | add a new numbered file under `sorter/apps/service/src/convo_gallery/migrations/`; never edit an applied one |
| Pipeline steps and CLI flags | `cli.py` (`run-all` branch), `pipeline.py` |
| Resume behaviour | `pipeline.py` (`reclaim_unfinished`, `run`) |
| Google Drive mode | `drive.py`, `ingest.py`, `scripts/drive_auth.py`, and the Drive branch of `process.py` |
| Test floors | `scripts/check.sh` (raise only) |
| What the public-tree scan bans | `sorter/tests/test_public_tree.py` |

## 8. Glossary

- Embedding: a list of 512 numbers that describes a face. Two photos of one person give vectors that point in nearly the same direction.
- Cosine distance: 1 minus the cosine of the angle between two embeddings. Zero means identical direction. The thresholds in this repo are cosine distances: lower means more alike.
- Cluster: a group of faces judged to be one person. The database table `clusters` holds them; one cluster becomes one person folder.
- Chinese Whispers: the clustering method described in 2.2.
- Roster: an optional folder of headshots, one per person, whose filenames, minus the extension and punctuation, become folder names.
- Preview: the shrunken JPEG (at most 2048 px) the detector reads instead of the original.
- Usable face: a detected face that passes the quality gate (size, detector score, sharpness).
- Singles: people seen in fewer photos than `MIN_PHOTOS`. They get no folder and are listed in `index.json`.
- Floor: the minimum number of passed tests a suite must report in `scripts/check.sh`.
- Marker file: `.event-face-sorter`, written into the sorted folder so the tool only ever deletes a folder it created.
- Model space: the set of embeddings made by one model. Only embeddings from the same model can be compared.
