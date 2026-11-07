#!/usr/bin/env bash
# Extract the five organizer checks (unchanged) from the pinned core commit into .cache/.
# Read-only for the remote: only `git fetch` of the SomeShit branch.
set -euo pipefail
CORE_SHA="${CORE_SHA:-496d8cdabfe215ae1c6a740d964df9189382196b}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/.cache/core-$CORE_SHA"
if [ -f "$DEST/.complete" ]; then echo "$DEST/checks"; exit 0; fi
if ! git -C "$ROOT" cat-file -e "$CORE_SHA^{commit}" 2>/dev/null; then
  git -C "$ROOT" fetch --quiet origin SomeShit
fi
rm -rf "$DEST"; mkdir -p "$DEST"
git -C "$ROOT" archive "$CORE_SHA" checks examples | tar -x -C "$DEST"
touch "$DEST/.complete"
echo "$DEST/checks"
