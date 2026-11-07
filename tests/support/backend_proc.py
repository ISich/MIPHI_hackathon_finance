"""Start/stop a REAL backend process for opt-in tests (restart, selftest). Loopback only, own DD_HOME.

All paths are resolved to absolute before the child gets a different cwd (CR #1). Only the Popen
child started here is ever signalled.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def backend_dir() -> Path | None:
    raw = os.environ.get("QA_BACKEND_DIR")
    return Path(raw).expanduser().resolve() if raw else None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def organizer_checks() -> Path:
    out = subprocess.run([str(ROOT / "scripts" / "fetch_core_checks.sh")], capture_output=True, text=True, check=True)
    return Path(out.stdout.strip().splitlines()[-1])


@dataclass
class Backend:
    proc: subprocess.Popen
    port: int
    home: Path
    log: Path
    mode: str = ""

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self, sig_kill: bool = False) -> None:
        if self.proc.poll() is None:
            (self.proc.kill if sig_kill else self.proc.terminate)()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _socket_owner_pids(port: int) -> set[int]:
    """PIDs listening on 127.0.0.1:port (ss shows pids for processes of the current user)."""
    out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True, check=False).stdout
    return {int(p) for p in re.findall(r"pid=(\d+),", out)}


def start_backend(home: Path, roots: dict[str, Path], mode: str = "builtin-only", port: int | None = None,
                  extra_env: dict[str, str] | None = None) -> Backend:
    bdir = backend_dir()
    if bdir is None:
        raise RuntimeError("QA_BACKEND_DIR not set")
    python = bdir / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"backend python missing: {python}")
    home = home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    port = port or free_port()
    if _port_in_use(port):  # CR2 #5: never start (and later trust /health) on a port someone else holds
        raise RuntimeError(f"port {port} on 127.0.0.1 is already in use; refusing to test an unknown server")
    checks = organizer_checks()
    env = {k: v for k, v in os.environ.items() if not k.startswith("DD_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", DD_HOME=str(home), DD_EXECUTION_MODE=mode, DD_EMBEDDED_WORKER="1",
               DD_CHECKS_DIR=str(checks), DD_WORKER_LEASE_SECONDS="3", DD_CHECK_TIMEOUT_SECONDS="5",
               DD_DATA_ROOTS=",".join([f"examples={checks.parent / 'examples'}"] +
                                      [f"{k}={Path(v).resolve()}" for k, v in roots.items()]))
    env.update(extra_env or {})
    log = home.parent / f"server-{port}.log"
    proc = subprocess.Popen([str(python), "-m", "uvicorn", "dd_backend.app:create_app", "--factory",
                             "--host", "127.0.0.1", "--port", str(port), "--app-dir", str(bdir)],
                            cwd=str(home.parent), env=env, stdout=log.open("ab"), stderr=subprocess.STDOUT)
    backend = Backend(proc, port, home, log, mode)
    try:
        _await_identity(backend, mode)
    except BaseException:
        backend.stop(sig_kill=True)  # CR5 #5: every unsuccessful startup path terminates the child
        raise
    return backend


def _await_identity(backend: Backend, mode: str) -> None:
    proc, port = backend.proc, backend.port
    foreign_streak = 0
    for _ in range(150):
        if proc.poll() is not None:
            raise AssertionError("backend exited during startup:\n" + backend.log.read_text())
        owners = _socket_owner_pids(port)
        if proc.pid in owners:
            foreign_streak = 0
            try:
                healthy = httpx.get(backend.url + "/health", timeout=1).status_code == 200
                session = httpx.get(backend.url + "/api/session", timeout=5).json()
            except httpx.HTTPError:
                healthy, session = False, None
            if healthy:
                if not isinstance(session, dict):
                    raise AssertionError(f"/api/session is not a JSON object: {session!r}")
                if proc.poll() is not None or proc.pid not in _socket_owner_pids(port):
                    raise AssertionError(f"port {port} no longer owned by launched pid {proc.pid}")
                if session.get("execution_mode") != mode:
                    raise AssertionError(f"server reports execution_mode={session.get('execution_mode')!r}, "
                                         f"expected {mode!r}")
                return
        elif owners:
            # Only a STABLE foreign owner counts (ss may briefly list a socket during bind/startup).
            foreign_streak += 1
            if foreign_streak >= 10:
                raise AssertionError(f"port {port} is held by pids {owners}, not launched pid {proc.pid}")
        else:
            foreign_streak = 0
        time.sleep(0.2)
    raise AssertionError("backend did not start:\n" + backend.log.read_text())
