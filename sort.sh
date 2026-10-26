#!/usr/bin/env bash
# event-face-sorter: rebuild the per-person folders after renaming people in the gallery.
# It does not detect faces again. Usage:  ./sort.sh [--min-photos N] [--mode copy|hardlink|symlink]
# With no flags it reuses the settings of the last run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi

exec "$ROOT/sorter/.venv/bin/python" -m convo_gallery.cli sort "$@"
