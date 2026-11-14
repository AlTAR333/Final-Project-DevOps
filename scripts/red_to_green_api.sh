#!/usr/bin/env bash
# Red-to-green demonstration for the API layer (owner: Armand).
#
#   1. GREEN: the planted-bug test passes on the correct code.
#   2. RED:   plant an off-by-one in api/validation.py (quantity 20 refused); the test must fail.
#   3. GREEN: repair the code; the test passes again.
#
# Usage (from anywhere in the repo):  bash scripts/red_to_green_api.sh
# The bug is always removed again, even if the script is interrupted.

set -u
cd "$(git rev-parse --show-toplevel)" || exit 1

TEST="tests/unit/test_planted_bug.py"
PATCH="scripts/planted_bug_quantity.patch"
TARGET="api/validation.py"
planted=0

repair() {
  if [ "$planted" -eq 1 ]; then
    git apply -R "$PATCH" && planted=0
  fi
}
trap repair EXIT INT TERM

if ! git diff --quiet -- "$TARGET"; then
  echo "Refusing to start: $TARGET has uncommitted changes. Commit or stash them first."
  exit 1
fi

echo "=== 1/3 GREEN: correct code ==="
python -m pytest -q "$TEST" || { echo "Baseline must be green before the demo."; exit 1; }

echo
echo "=== 2/3 RED: planting the bug ($PATCH) ==="
git apply "$PATCH" || exit 1
planted=1
git --no-pager diff --stat -- "$TARGET"
if python -m pytest -q "$TEST"; then
  echo "ERROR: the test did NOT catch the planted bug."
  exit 1
fi
echo "-> the test failed as expected (this is the red run)."

echo
echo "=== 3/3 GREEN: repairing the bug ==="
repair
python -m pytest -q "$TEST" || exit 1

echo
echo "Red-to-green demonstrated: fails with the bug, passes once repaired."
