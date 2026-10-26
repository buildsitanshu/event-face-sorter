#!/usr/bin/env bash
# The repo's own check: the privacy scan, then the three test suites, each inside its own venv. Non-zero exit on any failure.
# Each suite must also pass at least its floor of tests, and its final summary line must name no skipped,
# deselected or xfail test, so a suite that collects but skips tests cannot exit green. Raise a floor when you add tests; never lower it.
# Usage: bash scripts/check.sh [--smoke]
#   --smoke  after the suites pass, run the end-to-end proof on a generated fixture (scripts/smoke.py)
set -uo pipefail
cd "$(dirname "$0")/.."
smoke=0
case "${1:-}" in
  "") ;;
  --smoke) smoke=1 ;;
  *) echo "usage: bash scripts/check.sh [--smoke]" >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { echo "usage: bash scripts/check.sh [--smoke]" >&2; exit 2; }
fail=0
esc="$(printf '\033')"
# The final pytest summary line of a log, with colour codes stripped.
final_line() { tail -n 1 "$1" | sed "s/${esc}\[[0-9;]*m//g"; }
# A final line is clean only when it says "passed" and names no skipped, deselected or xfail test:
# a test that did not run is not a pass, whatever the exit code says.
all_ran() { [[ "$1" == *passed* && "$1" != *skipped* && "$1" != *deselected* && "$1" != *xfail* ]]; }
# The privacy scan runs as its own step first, so its result is never folded into a suite count.
echo "=== privacy scan ==="
if [ ! -x sorter/.venv/bin/python ]; then
  echo "missing sorter/.venv: run ./setup.sh first"; fail=1
elif [ ! -f sorter/tests/test_public_tree.py ]; then
  echo "PRIVACY SCAN FAIL: sorter/tests/test_public_tree.py is missing"; fail=1
else
  log="$(mktemp -t efs-check.XXXXXX)"
  ( cd sorter && ./.venv/bin/python -m pytest -q -p no:cacheprovider --color=no tests/test_public_tree.py ) 2>&1 | tee "$log"
  rc="${PIPESTATUS[0]}"
  last="$(final_line "$log")"
  rm -f "$log"
  if [ "$rc" -ne 0 ]; then
    echo "PRIVACY SCAN FAIL: exit=$rc"; fail=1
  elif ! all_ran "$last"; then
    echo "PRIVACY SCAN FAIL: skipped or deselected tests"; fail=1
  else
    echo "privacy scan: ok"
  fi
fi
for entry in face-recognition:4 video-frame-reader:2 sorter:160; do
  t="${entry%%:*}"; floor="${entry##*:}"
  echo "=== $t ==="
  if [ ! -x "$t/.venv/bin/python" ]; then echo "missing $t/.venv: run ./setup.sh first"; fail=1; continue; fi
  log="$(mktemp -t efs-check.XXXXXX)"
  ( cd "$t" && ./.venv/bin/python -m pytest -q -p no:cacheprovider --color=no ) 2>&1 | tee "$log"
  rc="${PIPESTATUS[0]}"
  echo "exit=$rc"
  [ "$rc" -ne 0 ] && fail=1
  # The count comes from the FINAL summary line only (so a warning or test name saying "999 passed" cannot be read),
  # with colour codes stripped. A final line holding more than one "N passed" is ambiguous, so it counts as unreadable.
  last="$(final_line "$log")"
  rm -f "$log"
  passed="$(printf '%s\n' "$last" | grep -oE '(^|[ ,])[0-9]+ passed' | grep -oE '[0-9]+')"
  if ! all_ran "$last"; then
    echo "FLOOR FAIL: $t has skipped or deselected tests"
    fail=1
  fi
  if ! [[ "$passed" =~ ^[0-9]+$ ]]; then
    echo "FLOOR FAIL: $t count unreadable"
    fail=1
    continue
  fi
  if [ "$passed" -lt "$floor" ]; then
    echo "FLOOR FAIL: $t passed $passed tests, floor is $floor"
    fail=1
  else
    echo "floor ok: $t passed $passed of at least $floor"
  fi
done
if [ "$smoke" -eq 1 ]; then
  if [ "$fail" -eq 0 ]; then
    echo "=== smoke ==="
    sorter/.venv/bin/python scripts/smoke.py
    rc=$?
    echo "smoke exit=$rc"
    [ "$rc" -ne 0 ] && fail=1
  else
    echo "smoke skipped: a suite failed"
  fi
fi
exit $fail
