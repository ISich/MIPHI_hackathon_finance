"""Runtime configuration from environment variables (no secrets are read here)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXECUTION_MODES = ("builtin-only", "trusted-local")
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


class SettingsError(ValueError):
    pass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if value <= 0:
        raise SettingsError(f"{name} must be positive")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _roots(raw: str) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        if "=" not in item:
            raise SettingsError("DD_DATA_ROOTS entries must be name=path")
        name, path = item.split("=", 1)
        name = name.strip()
        if not name.replace("-", "").replace("_", "").isalnum():
            raise SettingsError(f"Invalid data root name: {name!r}")
        roots[name] = Path(path.strip()).expanduser()
    return roots


def default_core_dir() -> Path:
    sha = (BACKEND_DIR / "CORE_COMMIT").read_text().strip()
    return BACKEND_DIR / ".core" / sha


@dataclass(frozen=True)
class Settings:
    home: Path
    data_roots: dict[str, Path]
    checks_dir: Path
    execution_mode: str
    embedded_worker: bool
    run_timeout_seconds: int
    check_timeout_seconds: int
    max_code_bytes: int
    max_output_bytes: int
    max_log_bytes: int
    max_memory_mb: int
    worker_lease_seconds: int
    cookie_secure: bool
    report_ui_base: str
    bind_host: str
    expected_core_commit: str = field(default="")

    @property
    def db_path(self) -> Path:
        return self.home / "backend.sqlite3"

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @property
    def scripts_dir(self) -> Path:
        return self.home / "scripts"


def load_settings() -> Settings:
    core = default_core_dir()
    home = Path(os.environ.get("DD_HOME") or BACKEND_DIR / "var").expanduser()
    roots_raw = os.environ.get("DD_DATA_ROOTS")
    if roots_raw is None:
        roots_raw = f"examples={core / 'examples'}"
    mode = os.environ.get("DD_EXECUTION_MODE", "builtin-only").strip()
    if mode not in EXECUTION_MODES:
        raise SettingsError(f"DD_EXECUTION_MODE must be one of {EXECUTION_MODES}")
    return Settings(
        home=home.resolve(),
        data_roots=_roots(roots_raw),
        checks_dir=Path(os.environ.get("DD_CHECKS_DIR") or core / "checks").expanduser(),
        execution_mode=mode,
        embedded_worker=_bool("DD_EMBEDDED_WORKER", True),
        run_timeout_seconds=_int("DD_RUN_TIMEOUT_SECONDS", 900),
        check_timeout_seconds=_int("DD_CHECK_TIMEOUT_SECONDS", 120),
        max_code_bytes=_int("DD_MAX_CODE_BYTES", 256 * 1024),
        max_output_bytes=_int("DD_MAX_OUTPUT_BYTES", 4 * 1024**3),
        max_log_bytes=_int("DD_MAX_LOG_BYTES", 1024 * 1024),
        max_memory_mb=_int("DD_MAX_MEMORY_MB", 6144),
        worker_lease_seconds=_int("DD_WORKER_LEASE_SECONDS", 15),
        cookie_secure=_bool("DD_COOKIE_SECURE", False),
        report_ui_base=os.environ.get("DD_REPORT_UI_BASE", "http://127.0.0.1:5173"),
        bind_host=os.environ.get("DD_BIND_HOST", "127.0.0.1"),
        expected_core_commit=(BACKEND_DIR / "CORE_COMMIT").read_text().strip(),
    )
