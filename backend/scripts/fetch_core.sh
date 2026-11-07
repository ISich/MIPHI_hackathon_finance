#!/usr/bin/env bash
# Fetch a read-only snapshot of the D1/D4 core branch assets (checks/, examples/, tests/)
# at the pinned commit into backend/.core/<sha>/. Uses the repository's configured origin.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sha="$(tr -d '[:space:]' < "$here/CORE_COMMIT")"
dest="$here/.core/$sha"
if [ -f "$dest/.complete" ]; then echo "$dest"; exit 0; fi
git -C "$here" cat-file -e "$sha^{commit}" 2>/dev/null || git -C "$here" fetch --quiet origin "$sha"
rm -rf "$dest.partial" && mkdir -p "$dest.partial"
top="$(git -C "$here" rev-parse --show-toplevel)"
git -C "$top" archive "$sha" checks examples tests | tar -x -C "$dest.partial"
chmod -R a-w "$dest.partial"/checks "$dest.partial"/examples
touch "$dest.partial/.complete"
rm -rf "$dest" && mv "$dest.partial" "$dest"
echo "$dest"
