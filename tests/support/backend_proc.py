"""Start/stop a REAL backend process for opt-in tests (restart, selftest). Loopback only, own DD_HOME.

All paths are resolved to absolute before the child gets a different cwd (CR #1). Only the Popen
child started here is ever signalled.
"""
from __future__ import annotations

import os
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
    backend = Backend(proc, port, home, log)
    for _ in range(150):
        if proc.poll() is not None:
            raise AssertionError("backend exited during startup:\n" + log.read_text())
        try:
            if httpx.get(backend.url + "/health", timeout=1).status_code == 200:
                if proc.poll() is not None:
                    raise AssertionError("launched backend died; another process answers " + backend.url)
                return backend
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    backend.stop(sig_kill=True)
    raise AssertionError("backend did not start:\n" + log.read_text())
