from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

CORE_SHA = os.environ.get("CORE_SHA", (ROOT / "CORE_COMMIT").read_text().strip())


@pytest.fixture(scope="session")
def organizer_checks_dir() -> Path:
    """The five organizer checks, byte-for-byte from the pinned core commit."""
    explicit = os.environ.get("CORE_CHECKS_DIR")
    if explicit:
        path = Path(explicit)
    else:
        result = subprocess.run([str(ROOT / "scripts" / "fetch_core_checks.sh")], capture_output=True,
                                text=True, env={**os.environ, "CORE_SHA": CORE_SHA}, check=False)
        if result.returncode != 0:
            pytest.fail("cannot fetch organizer checks: " + result.stderr)
        path = Path(result.stdout.strip().splitlines()[-1])
    files = sorted(path.glob("check_*.py"))
    assert len(files) == 5, f"expected five organizer checks in {path}, got {files}"
    return path
