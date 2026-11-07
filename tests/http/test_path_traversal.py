"""Path traversal / symlink escape / unrestricted paths (execution.md DatasetDescriptor, ScriptRef, ArtifactRef)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from support.http_api import assert_envelope

BAD_PATHS = ["../", "../../etc", "/etc", "/etc/passwd", "examples/../../..", "..\\..\\windows", "a/../../b",
             "%2e%2e/%2e%2e", "~/.ssh", "\x00"]


@pytest.mark.parametrize("bad", BAD_PATHS)
def test_dataset_paths_cannot_leave_root(api_a, examples_root, bad):
    r = api_a.post("/api/datasets", {"name": "trav", "root": examples_root, "mode": "dirs", "before": bad,
                                     "after": bad}, key=None)
    body = assert_envelope(r, (400, 404, 422))
    assert "root:" not in r.text and "/home/" not in r.text, body


def test_unknown_root_rejected(api_a):
    r = api_a.post("/api/datasets", {"name": "x", "root": "/", "mode": "dirs", "before": "a", "after": "b"}, key=None)
    assert_envelope(r, 422)


def test_symlink_escape_rejected(api_a, fixture_root):
    """CR #6: the symlink target is a VALID dataset (see positive control), so only containment can reject it."""
    root, folder = fixture_root
    link = folder / "escape"
    assert link.is_symlink() and (link / "BEFORE" / "O01.json").is_file()
    assert not link.resolve().is_relative_to(folder.resolve())
    r = api_a.post("/api/datasets", {"name": "sym", "root": root, "mode": "dirs", "before": "escape/BEFORE",
                                     "after": "escape/AFTER"}, key=None)
    body = assert_envelope(r, 422)
    assert "ESCAPE" in body["code"] or "outside" in body["message"].lower(), body
    r = api_a.post("/api/datasets", {"name": "sym-file", "root": root, "mode": "files",
                                     "before": "escape/BEFORE/O01.json", "after": "escape/AFTER/O01.json"}, key=None)
    assert_envelope(r, 422)


def test_symlink_target_is_valid_dataset_positive_control(api_a):
    """The very same files registered through a root that legitimately contains them are accepted."""
    outside = os.environ.get("QA_OUTSIDE_ROOT")
    if not outside:
        pytest.skip("QA_OUTSIDE_ROOT not set: symlink rejection reason cannot be isolated - NOT VERIFIED")
    r = api_a.post("/api/datasets", {"name": "outside-ok", "root": outside, "mode": "dirs", "before": "BEFORE",
                                     "after": "AFTER"}, key=None)
    assert r.status_code == 201, r.text
    assert r.json()["revisions"][-1]["pairs"] == 2


@pytest.mark.parametrize("tail", ["artifacts/..%2F..%2Fbackend.sqlite3", "artifacts/%2e%2e", "code/..%2F..%2Fetc",
                                  "applications/..%2F..%2F..%2Fetc%2Fpasswd", "artifacts/" + "a" * 300])
def test_path_params_do_not_reach_filesystem(api_a, completed_example_run, tail):
    run_id = completed_example_run["final"]["run_id"]
    r = api_a.get(f"/api/runs/{run_id}/{tail}")
    assert r.status_code in (400, 404, 422), (r.status_code, r.text[:200])
    assert "root:x:" not in r.text and "SQLite format" not in r.text


def test_uploaded_script_filename_cannot_traverse(api_a):
    """CR #6: check filesystem effects, not only returned metadata."""
    marker = f"QA_TRAVERSAL_MARKER_{uuid.uuid4().hex}"
    files = {"file": ("../../evil_qa.py", f"# {marker}\nx = 1\n".encode(), "text/x-python")}
    r = api_a.http.post("/api/scripts/upload", data={"kind": "check", "name": "evil"}, files=files)
    if r.status_code == 201:
        assert "/" not in (r.json().get("filename") or "") and ".." not in (r.json().get("filename") or ""), r.json()
    else:
        assert_envelope(r, (400, 422))
    home = os.environ.get("QA_SERVER_HOME")
    if not home:
        pytest.skip("QA_SERVER_HOME not set: filesystem effects not observable - metadata only checked")
    home_path = Path(home).resolve()
    scope = home_path.parent  # the launcher's private work dir: home, fixtures, logs
    stray = [p for p in scope.rglob("evil_qa.py")]
    assert stray == [], stray
    for path in scope.rglob("*"):
        if path.is_file() and not path.is_relative_to(home_path) and path.stat().st_size < 1_000_000:
            assert marker.encode() not in path.read_bytes(), f"upload content written outside DD_HOME: {path}"


def test_uploaded_non_python_rejected(api_a):
    files = {"file": ("evil.sh", b"rm -rf /\n", "text/plain")}
    r = api_a.http.post("/api/scripts/upload", data={"kind": "check", "name": "evil"}, files=files)
    assert_envelope(r, (400, 422))
