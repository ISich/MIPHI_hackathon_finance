"""Self-tests of the QA launchers (CR #1, #2). They run the real scripts against a real backend checkout.

Opt-in: QA_BACKEND_DIR=<backend checkout with .venv> (absolute or relative to the repository root).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = os.environ.get("QA_BACKEND_DIR")
pytestmark = [pytest.mark.slow, pytest.mark.skipif(not BACKEND, reason="QA_BACKEND_DIR not set - NOT VERIFIED")]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _relative_backend() -> str:
    return os.path.relpath(Path(BACKEND).resolve(), ROOT)


def _suite(mode: str, *pytest_args: str, env_extra: dict | None = None, timeout: int = 600):
    env = {**os.environ, "BACKEND_DIR": _relative_backend(), "QA_PORT": str(_free_port()), **(env_extra or {})}
    env.pop("QA_BASE_URL", None)
    return subprocess.run(["scripts/run_http_suite.sh", mode, *pytest_args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout)


def test_run_http_suite_accepts_relative_backend_dir():
    """CR #1: README documents BACKEND_DIR=../MIPHI_hackathon_finance/backend (relative)."""
    assert not os.path.isabs(_relative_backend())
    proc = _suite("builtin-only", "tests/http/test_system.py", "-q", "-k", "health")
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert " passed" in proc.stdout and "failed" not in proc.stdout and "error" not in proc.stdout


class _Impostor(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, *args):
        pass


def test_run_http_suite_refuses_busy_port_instead_of_testing_another_server():
    """CR #2: an unrelated server already on the port must not be tested in place of the launched one."""
    impostor = ThreadingHTTPServer(("127.0.0.1", 0), _Impostor)
    port = impostor.server_address[1]
    threading.Thread(target=impostor.serve_forever, daemon=True).start()
    try:
        proc = _suite("builtin-only", "tests/http/test_system.py", "-q", "-k", "health",
                      env_extra={"QA_PORT": str(port)}, timeout=120)
    finally:
        impostor.shutdown()
    assert proc.returncode != 0, proc.stdout[-2000:]
    assert "passed" not in proc.stdout, "pytest ran against the impostor"
    assert "port" in (proc.stdout + proc.stderr).lower()


def test_http_suite_rejects_server_in_other_execution_mode():
    """CR #2: QA_EXECUTION_MODE must match what the server reports, else refusal tests are silently skipped."""
    proc = _suite("builtin-only", "tests/http/test_system.py", "-q", "-k", "health",
                  env_extra={"QA_FORCE_EXPECTED_MODE": "trusted-local"})
    assert proc.returncode != 0
    assert "execution_mode" in proc.stdout, proc.stdout[-2000:]


def test_restart_test_accepts_relative_backend_dir():
    """CR #1: tests/restart resolves QA_BACKEND_DIR before changing cwd."""
    env = {**os.environ, "QA_BACKEND_DIR": _relative_backend()}
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/restart", "-q"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=400)
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert "1 passed" in proc.stdout


def test_start_backend_refuses_port_answered_by_another_process(tmp_path):
    """CR2 #5: the Python launcher must not accept /health from an unrelated process on its port."""
    from support.backend_proc import start_backend

    impostor = ThreadingHTTPServer(("127.0.0.1", 0), _Impostor)
    port = impostor.server_address[1]
    threading.Thread(target=impostor.serve_forever, daemon=True).start()
    try:
        with pytest.raises((AssertionError, RuntimeError)) as err:
            backend = start_backend(tmp_path / "home", {}, port=port)
            backend.stop()  # only reached if the launcher wrongly accepted the impostor
    finally:
        impostor.shutdown()
    assert "port" in str(err.value).lower()


def test_start_backend_verifies_execution_mode_and_socket_owner(tmp_path):
    from support.backend_proc import start_backend

    backend = start_backend(tmp_path / "home", {}, mode="trusted-local")
    try:
        assert backend.mode == "trusted-local" and backend.proc.poll() is None
    finally:
        backend.stop()


STALLING_BACKEND = """#!/usr/bin/env python3
# TEST DOUBLE for the launcher self-test: binds the requested port, accepts connections, never answers.
import socket, sys, time
port = int(sys.argv[sys.argv.index("--port") + 1])
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port)); s.listen(50)
held = []
while True:
    conn, _ = s.accept(); held.append(conn)
"""


def test_run_http_suite_startup_is_bounded_when_backend_stalls(tmp_path):
    """CR3 #6: a process that accepts connections but never responds must not hang the launcher."""
    import time

    fake = tmp_path / "stalling_python"
    fake.write_text(STALLING_BACKEND)
    fake.chmod(0o755)
    started = time.monotonic()
    try:
        proc = _suite("builtin-only", "tests/http/test_system.py", "-q", "-k", "health",
                      env_extra={"BACKEND_PY": str(fake), "QA_STARTUP_TIMEOUT": "20"}, timeout=150)
    except subprocess.TimeoutExpired:
        pytest.fail("run_http_suite.sh hung on a stalling backend (no curl/startup deadline)")
    assert proc.returncode != 0
    assert "passed" not in proc.stdout
    assert time.monotonic() - started < 120


def test_run_http_suite_cleanup_is_bounded_when_backend_ignores_sigterm(tmp_path):
    """CR5 #4: a child that ignores SIGTERM must still be stopped (SIGKILL after a grace period), launcher exits."""
    import time

    fake = tmp_path / "stubborn_python"
    fake.write_text(STALLING_BACKEND.replace("import socket, sys, time\n",
                                             "import socket, sys, time, signal\n"
                                             "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"))
    fake.chmod(0o755)
    started = time.monotonic()
    try:
        proc = _suite("builtin-only", "tests/http/test_system.py", "-q", "-k", "health",
                      env_extra={"BACKEND_PY": str(fake), "QA_STARTUP_TIMEOUT": "10", "QA_STOP_TIMEOUT": "5"},
                      timeout=90)
    except subprocess.TimeoutExpired:
        subprocess.run(["pkill", "-KILL", "-f", str(fake)], check=False)
        pytest.fail("run_http_suite.sh cleanup hung on a backend that ignores SIGTERM")
    assert proc.returncode != 0 and time.monotonic() - started < 60
    alive = subprocess.run(["pgrep", "-f", str(fake)], capture_output=True, text=True).stdout.strip()
    assert alive == "", f"launched backend still running: {alive}"


MALFORMED_BACKEND = """#!/usr/bin/env python3
# TEST DOUBLE: healthy /health, malformed /api/session (%(payload)r).
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int(sys.argv[sys.argv.index("--port") + 1])
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status": "ok"}' if self.path == "/health" else %(payload)r
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


@pytest.mark.parametrize("payload", [b"not json", b"[1, 2]"])
def test_start_backend_stops_child_on_malformed_session(tmp_path, monkeypatch, payload):
    """CR5 #5: malformed /api/session must not leak the launched process."""
    from support import backend_proc

    fake_dir = tmp_path / "fake_backend"
    (fake_dir / ".venv" / "bin").mkdir(parents=True)
    fake = fake_dir / ".venv" / "bin" / "python"
    fake.write_text(MALFORMED_BACKEND % {"payload": payload})
    fake.chmod(0o755)
    monkeypatch.setenv("QA_BACKEND_DIR", str(fake_dir))
    launched = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        p = real_popen(*args, **kwargs)
        if "uvicorn" in map(str, p.args if isinstance(p.args, list) else [p.args]):
            launched.append(p)  # only the backend child, not fetch_core_checks.sh
        return p

    monkeypatch.setattr(backend_proc.subprocess, "Popen", recording_popen)
    with pytest.raises(Exception):
        backend_proc.start_backend(tmp_path / "home", {})
    assert launched, "launcher did not start the fake"
    try:
        assert launched[0].poll() is not None, "launched backend leaked after failed startup"
    finally:
        if launched[0].poll() is None:
            launched[0].kill()
