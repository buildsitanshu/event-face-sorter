#!/usr/bin/env bash
# event-face-sorter: run the whole pipeline end to end.
# Usage:  ./run.sh --photos DIR [--people DIR] [--limit N] [--skip-video] [--workers N]
#                  [--min-photos N] [--sort-mode copy|hardlink|symlink]
#   Google Drive mode (second-class, see README):  ./run.sh --media <folderId> [--roster <folderId>]
# Settings can also come from .env (see .env.example). Relative paths are read from where you run it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

# load .env if present (CONVO_MEDIA_DIR, CONVO_ROSTER_DIR, CONVO_DATA_DIR, ...)
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi

exec "$ROOT/sorter/.venv/bin/python" -m convo_gallery.cli run-all "$@"
