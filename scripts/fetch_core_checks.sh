#!/usr/bin/env bash
# Extract the five organizer checks (unchanged) from the pinned core commit into .cache/.
# Read-only for the remote: only `git fetch` of the SomeShit branch.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE_SHA="${CORE_SHA:-$(cat "$ROOT/CORE_COMMIT")}"
DEST="$ROOT/.cache/core-$CORE_SHA"
if [ -f "$DEST/.complete" ]; then echo "$DEST/checks"; exit 0; fi
if ! git -C "$ROOT" cat-file -e "$CORE_SHA^{commit}" 2>/dev/null; then
  git -C "$ROOT" fetch --quiet origin SomeShit
fi
rm -rf "$DEST"; mkdir -p "$DEST"
git -C "$ROOT" archive "$CORE_SHA" checks examples | tar -x -C "$DEST"
touch "$DEST/.complete"
echo "$DEST/checks"
