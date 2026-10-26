# event-face-sorter: runbook for Claude Code

This repo sorts a folder of event photos and videos into one folder per person, by face, entirely on this machine. The rule above all others: the user's photo folder is read-only to you. Every output lands under `sorter/data/` (or `CONVO_DATA_DIR`), and nothing is uploaded anywhere.

Follow the sections in order. Every step has a command and the line of output that proves it worked. If a proof line is missing, stop and use the troubleshooting table in section 8.

## 1. Before you touch anything, ask the user three questions

1. What is the absolute path of the folder with the event photos? Does it also hold videos they want sorted?
2. Do they have one clear photo per person they want named (a headshot folder)? Where is it?
3. Where should the sorted copies go if the disk is small? The default is `sorter/data/sorted/` inside this repo. `--sort-mode hardlink` uses no extra space when the photos and the repo are on the same disk.

Then confirm the photo folder exists and count its files:

```bash
find "<dir>" -type f | wc -l
```

Proof: a number greater than 0. This is a sanity check only. The run's step 2 line `N files: jpeg=a, video=b, ...` is the total for every count you report; `find` also counts files the tool skips (dot-files, RAW, text). If it prints 0 or an error, ask the user for the correct path.

## 2. Setup

1. Check python3.12. Run `python3.12 --version`. Proof: first line `Python 3.12.x`. If missing: macOS `brew install python@3.12`; Debian or Ubuntu `sudo apt install python3.12 python3.12-venv`. On Windows, stop and recommend WSL2.
2. Check ffmpeg (needed only for videos). Run `ffmpeg -version`. Proof: first line starts with `ffmpeg version`. If missing: macOS `brew install ffmpeg`; Debian or Ubuntu `sudo apt install ffmpeg`.
3. Run `./setup.sh`. It takes 2 to 5 minutes. Proof: a line reading `setup complete.`
4. Run `bash scripts/check.sh --smoke`. The first run downloads the face model (about 350 MB), so allow a few minutes. Proof: the lines `privacy scan: ok`, `floor ok: face-recognition passed 4 of at least 4`, `floor ok: video-frame-reader passed 2 of at least 2`, `floor ok: sorter passed N of at least 160`, and the last line `smoke exit=0`. N is the real passed count and may be higher than the floor; the other two lines have the same shape with their own counts.
5. If step 4 fails, read the troubleshooting table in section 8, then stop and show the user the last 30 lines of the output. Never edit the floors in `scripts/check.sh` or any test to make it pass.

## 3. First run on the user's photos

1. Run `./run.sh --photos "<dir>" --limit 20`. Add `--people "<headshot dir>"` when headshots exist. Add `--skip-video` when the user does not want videos. Note the seconds the run takes.
2. Proof: the output ends with a line starting `DONE in`.
3. Read `sorter/data/sorted/index.json`. Report to the user, each as "n of total": people (folders in `people`), files written, singles (length of `singles`), no_faces (length of `no_faces`), unprocessed (the `unprocessed` value). Files written is `files_written` in the step 7/7 line of the run output.
4. Show the user the folder list: `ls sorter/data/sorted/`.
5. Ask whether the grouping looks right before the full run.
6. Estimate the full run: (total files / 20) times the seconds from step 1, then divide by 60 for minutes. Tell the user that number as an estimate. The `--limit 20` pass is the only throughput measurement; this repo records none for real photos.

## 4. Full run

1. Run `./run.sh --photos "<dir>"` with the same flags as section 3, minus `--limit`.
2. Progress lines print `...processed=N faces=M errors=E`. If it is interrupted, run the same command again; it resumes.
3. Proof: a line starting `DONE in`. Report the same counts as section 3 step 3, read from `sorter/data/sorted/index.json` and `sorter/data/sorted/README.txt`.

## 5. Show the result

1. Run `./view.sh`. Proof: the line `Gallery: http://127.0.0.1:3110/` followed by uvicorn's `Uvicorn running on http://127.0.0.1:3110`; if the port is busy the script prints `port 3110 is in use` and exits 3. Then run `PORT=3111 ./view.sh`.
2. Tell the user to open http://127.0.0.1:3110/ in a browser. There they can search, open a person, rename a person (type a name, press Save name), choose Download all for a zip, and open any original.
3. After renames, run `./sort.sh` to rebuild the folders with the new names. `./sort.sh` reuses the `--min-photos` and `--sort-mode` of the last run (stored in `sorter/data/sort-settings.json`); pass `--min-photos N` or `--mode M` to change them. It refuses with `no run found` when no run has happened in that data folder. Proof: a line `sort settings: ...` and a JSON block with `"people"` and `"files_written"`.
4. Stop the server with Ctrl-C.

## 6. Tuning

| Symptom | Fix |
|---|---|
| Too many `person-NNN` folders with 2 photos (guests, passers-by) | `--min-photos 5` |
| One person split across folders | give a headshot with `--people`, or rename both folders in the gallery |
| Videos are slow | `--skip-video`, or `CONVO_VIDEO_FPS=0.25` |
| Little disk space | `--sort-mode hardlink` |
| Outputs should go elsewhere | Put `CONVO_DATA_DIR=/path` in `.env` (copy `.env.example`) so `run.sh`, `view.sh` and `sort.sh` all use it; setting it inline on one command only affects that command. The folder must be outside the photo folder; `run.sh` refuses before writing anything otherwise. |
| The machine runs out of memory or turns sluggish during a run | `--workers 2` (each worker loads its own copy of the face model; the default is 8) |

## 7. Rules for Claude

- Never run with `--photos` pointing at `/`, `~`, or a system folder.
- Never delete or move files inside the photo folder.
- Never commit `sorter/data/`.
- Never lower a floor or skip a test.
- Report counts with denominators from `index.json`, never from memory.
- Keep everything local: no uploads, no cloud.
- If `bash scripts/check.sh --smoke` is red, stop and show the user. Do not patch around it.
- When the user asks for Google Drive mode, follow README section 6 and say that path is less tested.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `need python3.12 on PATH` | python3.12 is not installed or not on PATH | install it (section 2 step 1), open a new terminal, re-run `./setup.sh` |
| `WARNING: ffmpeg not found` | ffmpeg missing | install it (section 2 step 2); photos still work without it |
| Model download fails | network drop or full disk | check free disk, then retry the same command; the files land in `~/.insightface/models/antelopev2` |
| `refusing to clear ... it was not created by this tool` | the output folder already exists with other content | pick an empty or new folder with `CONVO_DATA_DIR=/path`; never delete the user's folder |
| `inside the photo folder` or `is inside the output folder` | outputs and photos overlap | set `CONVO_DATA_DIR` to a path outside the photo folder |
| `headshots folder not found: ...` | the `--people` path is wrong | fix the path (check spelling and quotes) |
| HEIC photos reported as `unreadable_image` | pillow-heif missing | re-run `./setup.sh` (it installs pillow-heif); else convert the photos to JPEG |
| `permission denied` on an external drive or the Photos library | macOS blocks the terminal app | grant the terminal app Full Disk Access in System Settings, or copy the photos to a normal folder |
| `port 3110 is in use` | another program holds the port | `PORT=3111 ./view.sh` |
| `no run found in ...` | sort.sh points at a data folder with no run | set the same `CONVO_DATA_DIR` as the run, or run `./run.sh` first |
| `FLOOR FAIL` | tests were removed or skipped | restore the tests; never lower the floor |
| `PRIVACY SCAN FAIL` | a private identifier, binary file or banned pattern is in the tree | remove it; never edit the scan |
| A run was interrupted (crash, power loss, Ctrl-C) | files may be left `claimed` | run the same command again; it resumes; the run prints "resumed N file(s)" |

## 9. Layout and glossary

```
sorter/               the app (Python module convo_gallery): pipeline, CLI, gallery viewer
face-recognition/     face detection, embedding, grouping library
video-frame-reader/   ffmpeg frame sampling library
scripts/              check.sh (privacy scan + tests + floors + smoke), smoke.py, drive_auth.py (Drive mode)
docs/                 HOW-IT-WAS-BUILT.md: how the system was built, decisions, limitations (read before changing code)
run.sh                run the pipeline
view.sh               serve the gallery on 127.0.0.1
sort.sh               rebuild person folders after renames
setup.sh              one-time install
.env.example          optional settings; copy to .env
```

- Person folder: one folder under `sorter/data/sorted/` holding a copy of every photo and video that person appears in.
- Headshot / roster: a folder with one clear photo per person, named `<Name>.jpg`; the filename becomes the folder name.
- Singles: people seen in fewer photos than `--min-photos`; they get no folder and are listed in `index.json`.
- no_faces: files where no usable face was found; listed in `index.json`.
- min-photos: the smallest number of photos a person needs to get a folder (default 2).
- Sort mode: how originals reach the person folders: `copy` (default), `hardlink` (no extra disk on the same drive), `symlink`.
