#!/usr/bin/env bash
# event-face-sorter: one-time setup. Creates an isolated venv per package and wires the
# editable installs. Safe to re-run. Requires python3.12 on PATH (and ffmpeg for videos).
set -euo pipefail
cd "$(dirname "$0")"

command -v python3.12 >/dev/null || { echo "need python3.12 on PATH"; exit 1; }
command -v ffmpeg     >/dev/null || echo "WARNING: ffmpeg not found, video processing will fail (brew install ffmpeg)"

for t in face-recognition video-frame-reader sorter; do
  echo "=== $t ==="
  ( cd "$t" && { [ ! -d .venv ] || ./.venv/bin/pip --version >/dev/null 2>&1 || { echo "  stale venv (folder moved?): recreating"; rm -rf .venv; }; } && python3.12 -m venv .venv && ./.venv/bin/pip install -q --upgrade pip && ./.venv/bin/pip install -q -e '.[dev]' )
done

# the sorter app composes the two libraries:
( cd sorter && ./.venv/bin/pip install -q -e ../face-recognition -e ../video-frame-reader )

echo
echo "setup complete."
echo "  1) bash scripts/check.sh --smoke    (proves the install works end to end)"
echo "  2) ./run.sh --photos \"/path/to/photos\" --limit 20    (a quick first pass)"
echo
echo "Note: the face model (InsightFace antelopev2) downloads to ~/.insightface on first run."
