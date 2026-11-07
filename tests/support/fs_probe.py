"""Filesystem boundary probe for upload traversal tests (CR2 #3). Pure functions, unit-tested in tests/selftest."""
from __future__ import annotations

from pathlib import Path


def escape_targets(home: Path, name: str, depth: int = 8) -> list[Path]:
    """Where a filename made of '../' segments (or an absolute path) could land: `name` directly inside every
    ancestor of DD_HOME (one level per '../'), up to `depth` levels. These lie OUTSIDE the permitted boundary."""
    home = home.resolve()
    return [p / name for p in list(home.parents)[:depth]]


def forbidden_copies(home: Path, name: str, marker: bytes, scan_root: Path, depth: int = 8) -> list[Path]:
    """Files that must NOT exist after an upload named `name` carrying `marker`:
    - `name` at any controlled escape target (ancestors of DD_HOME, even outside scan_root);
    - any file under scan_root but outside DD_HOME that has that name or contains the marker.
    Anything inside DD_HOME (the permitted storage boundary) is allowed, sanitized or not."""
    home = home.resolve()
    found = [p for p in escape_targets(home, name, depth) if p.exists()]
    for path in Path(scan_root).resolve().rglob("*"):
        if path.is_relative_to(home) or not path.is_file() or path in found:
            continue
        if path.name == name or (path.stat().st_size < 1_000_000 and marker in path.read_bytes()):
            found.append(path)
    return found
