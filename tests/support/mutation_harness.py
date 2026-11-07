"""Run HTTP test nodes against a REAL backend behind the mutating proxy (TEST DOUBLE, selftest only)."""
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from support.backend_proc import ROOT, start_backend
from support.mutating_proxy import make_proxy


@contextmanager
def backend_with_fixtures(workdir: Path, mode: str):
    fixtures = workdir / "fixtures"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_http_fixtures.py"), str(fixtures)], check=True,
                   capture_output=True)
    backend = start_backend(workdir / "home", {"qa": fixtures, "outside": workdir / "outside"}, mode=mode)
    try:
        yield backend, fixtures
    finally:
        backend.stop()


def run_nodes(backend_url: str, fixtures: Path, nodes: list[str], mutations: set[str],
              repo_root: Path = ROOT, timeout: int = 600) -> subprocess.CompletedProcess:
    proxy = make_proxy(backend_url, mutations)
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith("QA_")}
        env.update(QA_BASE_URL=f"http://127.0.0.1:{proxy.server_address[1]}", QA_FIXTURE_ROOT="qa",
                   QA_FIXTURE_DIR=str(fixtures), QA_OUTSIDE_ROOT="outside")
        return subprocess.run([sys.executable, "-m", "pytest", *nodes, "-q", "--no-header", "-rfEsx", "-p",
                               "no:cacheprovider"], cwd=repo_root, env=env, capture_output=True, text=True,
                              timeout=timeout)
    finally:
        proxy.shutdown()


def outcome(proc: subprocess.CompletedProcess) -> str:
    """'failed' if any test failed/errored, else 'passed' / 'xfailed' / 'skipped' by the summary line."""
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if " failed" in tail or " error" in tail:
        return "failed"
    for word in ("passed", "xfailed", "skipped"):
        if word in tail:
            return word
    return "unknown: " + tail
