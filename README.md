# event-face-sorter

Point it at a folder of event photos and videos. It finds every face locally on the CPU, groups the faces into people, copies every original into one folder per person, and gives you a local web gallery where you browse, rename people and download. Nothing leaves your machine, your photo folder is never modified, and you need no account and no GPU.

It began as a tool for a graduation ceremony, where many thousands of photos had to reach each graduate as "the photos you are in", using a shared Drive folder and registration headshots. A friend of the author wanted the same for an event with only a folder of photos, so it was generalised: local folder in, one folder per person out, headshots optional, nothing uploaded.

If you use Claude Code, open this folder in it and say "set this up for my photos". The runbook in `CLAUDE.md` walks it through every step.

## 1. Requirements

- macOS or Linux. Windows is untested; use WSL2.
- python3.12 (`brew install python@3.12`).
- ffmpeg, only if you have videos (`brew install ffmpeg`).
- About 350 MB of download for the face model on first run (the InsightFace antelopev2 pack). It is cached in `~/.insightface`: about 410 MB unpacked, and the 350 MB zip stays beside it.

## 2. Quick start

1. `./setup.sh` builds one virtual environment per package (2 to 5 minutes).
2. `bash scripts/check.sh --smoke` proves the install works. It must end with `smoke exit=0`.
3. `./run.sh --photos "/path/to/photos" --limit 20` runs a quick pass on 20 files per kind.
4. Look inside `sorter/data/sorted/`. Each folder is one person.
5. `./run.sh --photos "/path/to/photos"` runs the full job. Re-running resumes where it stopped.
6. `./view.sh` serves the gallery at http://127.0.0.1:3110/ (this machine only). Press Ctrl-C to stop it.

## 3. Headshots (optional)

Make a folder with one clear photo per person, named `<Name>.jpg` (for example `Asha Rao.jpg`). Pass it with `--people`:

```bash
./run.sh --photos "/path/to/photos" --people "/path/to/headshots"
```

People without a headshot become `person-001`, `person-002` and so on. Rename them in the gallery (type a name, press Save name), then run `./sort.sh` to rebuild the folders with the new names. `./sort.sh` does not detect faces again.

## 4. Outputs

All outputs are under `sorter/data/` (or `CONVO_DATA_DIR`).

- `sorted/` has one folder per person, plus `index.json` (who is in which folder, singles, photos with no faces, count of unprocessed files) and `README.txt`.
- `web/` is the gallery bundle that `./view.sh` serves.
- `gallery.db` is the SQLite database of files, faces and people.
- `previews/` and `crops/` hold the downsized photos and face crops the gallery shows.

Re-running is safe: finished files are skipped and an interrupted run resumes.

## 5. Options

| Option | Meaning |
|---|---|
| `--photos DIR` | folder of photos and videos to sort (read only) |
| `--people DIR` | optional folder of headshots, filename = name |
| `--limit N` | process at most N files per kind (photo, video), for a quick trial |
| `--skip-video` | photos only |
| `--workers N` | parallel worker processes (default 8) |
| `--min-photos N` | hide people seen in fewer than N photos (default 2) |
| `--sort-mode copy\|hardlink\|symlink` | how originals reach the person folders (default copy; hardlink uses no extra disk on the same drive) |
| `CONVO_DATA_DIR=DIR` | write outputs elsewhere. Put `CONVO_DATA_DIR=/path` in `.env` (copy `.env.example`) so `run.sh`, `view.sh` and `sort.sh` all use it; setting it inline on one command only affects that command. The folder must be outside the photo folder; `run.sh` refuses before writing anything otherwise. |
| `CONVO_VIDEO_FPS=N` | frames per second sampled from videos (default 0.5) |

The `classify` stage has two more knobs, used with `sorter/.venv/bin/python -m convo_gallery.cli classify` after a run: `--match-threshold` (default 0.40, how close a face must be to a headshot to take that name) and `--cluster-threshold` (default 0.35, how close faces must be to group together). Run it from the `sorter/` folder with `CONVO_DATA_DIR` set if you moved the outputs.

## 6. Google Drive mode (second-class)

This path was not exercised against a live Google account in this build. The local-folder path above is the tested one.

1. Create a Google Cloud project and enable the Drive API.
2. Create an OAuth client of type Desktop and download its client json.
3. Run `sorter/.venv/bin/python scripts/drive_auth.py <client_secret.json>` and approve read-only access in the browser.
4. Copy `.env.example` to `.env` and set `CONVO_ROOT_FOLDER_ID` (photos) and optionally `CONVO_ROSTER_FOLDER_ID` (headshots). A folder id is the part after `/folders/` in the folder URL.
5. Run `./run.sh`.

## 7. The self-check and what it proves

`bash scripts/check.sh` first runs the privacy scan (`sorter/tests/test_public_tree.py`) as its own step, which prints `privacy scan: ok` or `PRIVACY SCAN FAIL`. It then runs three pytest suites with passed-count floors of 4, 2 and 160; the real counts are printed on the floor lines. Each suite has a floor, so a suite that skips its tests cannot pass. `--smoke` builds a fixture from InsightFace's bundled sample image (8 photos and one 2-second clip), runs the whole pipeline twice (once without headshots, once with a one-person headshot folder), finds 6 faces, and asserts the folders, the names, byte-identical copies and untouched sources.

The fixture faces are cut from one group photo by the same detector that later finds them. So the smoke proves the wiring and copy integrity, not recognition accuracy on real event photos. Measured on an Apple M-series Mac, the smoke ran in 10 to 25 seconds including model load (10 seconds on a warm run, 25 seconds on the first run after setup).

## 8. Layout

```
sorter/               the app: pipeline, CLI, local gallery viewer (Python module convo_gallery)
face-recognition/     face detection, embedding and grouping library
video-frame-reader/   ffmpeg frame sampling library
scripts/              check.sh, smoke.py, drive_auth.py
docs/                 HOW-IT-WAS-BUILT.md: how the system was built, decisions, limitations (read before changing code)
run.sh                run the pipeline
view.sh               serve the gallery on 127.0.0.1
sort.sh               rebuild person folders after renaming
setup.sh              one-time install
CLAUDE.md             the runbook for Claude Code
```

The Python module keeps its historical name `convo_gallery`.

## 9. Privacy and limits

- Everything runs on your machine. The only network use is the one-time model download (and Google Drive, if you choose that mode).
- In local mode, RAW files are skipped; their JPEG siblings are used.
- HEIC photos are supported through pillow-heif.
- Videos are sampled at `CONVO_VIDEO_FPS` frames per second, so a face visible for less than one sampling interval can be missed.
- One person can split into two folders when lighting or angle differs. Give a headshot, or rename both folders in the gallery.
- A photo with many people is copied into every person's folder.

## License

MIT, see `LICENSE`.
