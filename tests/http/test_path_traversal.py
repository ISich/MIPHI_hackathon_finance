"""Path traversal / symlink escape / unrestricted paths (execution.md DatasetDescriptor, ScriptRef, ArtifactRef)."""
from __future__ import annotations

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
    root, folder = fixture_root
    assert (folder / "escape").is_symlink()
    r = api_a.post("/api/datasets", {"name": "sym", "root": root, "mode": "files", "before": "escape/etc/hostname",
                                     "after": "escape/etc/hostname"}, key=None)
    assert_envelope(r, 422)


@pytest.mark.parametrize("tail", ["artifacts/..%2F..%2Fbackend.sqlite3", "artifacts/%2e%2e", "code/..%2F..%2Fetc",
                                  "applications/..%2F..%2F..%2Fetc%2Fpasswd", "artifacts/" + "a" * 300])
def test_path_params_do_not_reach_filesystem(api_a, completed_example_run, tail):
    run_id = completed_example_run["final"]["run_id"]
    r = api_a.get(f"/api/runs/{run_id}/{tail}")
    assert r.status_code in (400, 404, 422), (r.status_code, r.text[:200])
    assert "root:x:" not in r.text and "SQLite format" not in r.text


def test_uploaded_script_filename_cannot_traverse(api_a):
    files = {"file": ("../../evil.py", b"x = 1\n", "text/x-python")}
    r = api_a.http.post("/api/scripts/upload", data={"kind": "check", "name": "evil"}, files=files)
    if r.status_code == 201:
        assert "/" not in (r.json().get("filename") or ""), r.json()
    else:
        assert_envelope(r, (400, 422))


def test_uploaded_non_python_rejected(api_a):
    files = {"file": ("evil.sh", b"rm -rf /\n", "text/plain")}
    r = api_a.http.post("/api/scripts/upload", data={"kind": "check", "name": "evil"}, files=files)
    assert_envelope(r, (400, 422))
