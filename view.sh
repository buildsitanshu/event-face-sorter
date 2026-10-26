#!/usr/bin/env bash
# event-face-sorter: serve the local gallery at http://127.0.0.1:${PORT:-3110}/ (this machine only).
# Usage:  ./view.sh        or   PORT=3111 ./view.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi

PORT="${PORT:-3110}"
rc=0
"$ROOT/sorter/.venv/bin/python" -c 'import socket,sys; s=socket.socket(); s.settimeout(0.2); rc=s.connect_ex(("127.0.0.1", int(sys.argv[1]))); s.close(); sys.exit(0 if rc else 3)' "$PORT" || rc=$?
if [ "$rc" -eq 3 ]; then
  echo "port $PORT is in use: try PORT=$((PORT+1)) ./view.sh"
  exit 3
fi
echo "Gallery: http://127.0.0.1:$PORT/"
exec "$ROOT/sorter/.venv/bin/uvicorn" convo_gallery.api:app --host 127.0.0.1 --port "$PORT"
