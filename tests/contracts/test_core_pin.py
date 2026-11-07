"""The QA suite must run against exactly the pinned core (regression: an unnoticed core/pin mismatch)."""
from __future__ import annotations

import importlib.metadata
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_requirements_pin_equals_core_commit():
    pinned = (ROOT / "CORE_COMMIT").read_text().strip()
    req = re.search(r"decision-diff-core @ git\+\S+@([0-9a-f]{40})", (ROOT / "requirements-qa.txt").read_text())
    assert req and req.group(1) == pinned


def test_installed_core_is_the_pinned_commit():
    pinned = (ROOT / "CORE_COMMIT").read_text().strip()
    raw = importlib.metadata.distribution("decision-diff-core").read_text("direct_url.json")
    assert raw, "decision-diff-core was not installed from a pinned VCS commit"
    assert json.loads(raw)["vcs_info"]["commit_id"] == pinned
