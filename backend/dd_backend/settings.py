"""Runtime configuration from environment variables (no secrets are read here)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXECUTION_MODES = ("builtin-only", "sandboxed", "trusted-local")
# Modes in which workspace/file Python is executed at all (sandboxed: Landlock+seccomp, see sandbox.py).
CUSTOM_EXECUTION_MODES = ("sandboxed", "trusted-local")
AI_RESPONSE_FORMATS = ("json_schema", "json_object", "none")
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


LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def split_host(value: str) -> str:
    """'Host' header -> lowercase host without port (IPv6 kept in brackets)."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[: value.find("]") + 1] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _origin(url: str) -> str:
    from urllib.parse import urlsplit
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SettingsError(f"Invalid origin: {url!r}")
    return f"{parts.scheme}://{parts.netloc.lower()}"


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
    max_input_file_bytes: int = field(default=64 * 1024 * 1024)
    max_check_result_bytes: int = field(default=16 * 1024 * 1024)
    max_report_bytes: int = field(default=64 * 1024 * 1024)
    allowed_hosts: frozenset = field(default=frozenset())
    # AI opinion (FR-024). The API key is NOT part of Settings: ai_opinion.api_key() reads it at call time.
    ai_base_url: str = field(default="https://openrouter.ai/api/v1")
    ai_model: str = field(default="")
    ai_timeout_seconds: int = field(default=90)
    ai_max_output_tokens: int = field(default=2500)
    ai_response_format: str = field(default="json_schema")
    ai_openrouter_privacy: bool = field(default=True)
    sandbox_max_open_files: int = field(default=512)

    @property
    def custom_execution_enabled(self) -> bool:
        return self.execution_mode in CUSTOM_EXECUTION_MODES

    @property
    def sandboxed(self) -> bool:
        return self.execution_mode == "sandboxed"

    @property
    def db_path(self) -> Path:
        return self.home / "backend.sqlite3"

    @property
    def signing_key_path(self) -> Path:
        return self.home / "pivot-locator.key"

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
    hosts_raw = os.environ.get("DD_ALLOWED_HOSTS", "127.0.0.1,localhost,::1")
    allowed_hosts = frozenset(split_host(h) if h.strip() not in ("::1",) else "::1"
                              for h in hosts_raw.split(",") if h.strip())
    allowed_hosts = allowed_hosts | ({"[::1]"} if "::1" in allowed_hosts else set())
    if mode == "trusted-local" and not allowed_hosts <= LOOPBACK_NAMES:
        raise SettingsError("trusted-local execution allows only loopback DD_ALLOWED_HOSTS "
                            f"({sorted(LOOPBACK_NAMES)}), got {sorted(allowed_hosts)}")
    if os.environ.get("DD_ALLOWED_ORIGINS"):
        raise SettingsError("DD_ALLOWED_ORIGINS was removed: cross-origin browser access is not supported. "
                            "Deploy UI and API same-origin (nginx /api -> backend, or a dev proxy keeping Host)")
    ai_base = os.environ.get("DD_AI_BASE_URL", "").strip() or "https://openrouter.ai/api/v1"
    _origin(ai_base)
    ai_format = os.environ.get("DD_AI_RESPONSE_FORMAT", "").strip() or "json_schema"
    if ai_format not in AI_RESPONSE_FORMATS:
        raise SettingsError(f"DD_AI_RESPONSE_FORMAT must be one of {AI_RESPONSE_FORMATS}")
    ui_base = os.environ.get("DD_REPORT_UI_BASE", "http://127.0.0.1:5173")
    _origin(ui_base)  # validated: only used as the absolute link target inside HTML reports
    return Settings(
        allowed_hosts=allowed_hosts,
        max_input_file_bytes=_int("DD_MAX_INPUT_FILE_BYTES", 64 * 1024 * 1024),
        max_check_result_bytes=_int("DD_MAX_CHECK_RESULT_BYTES", 16 * 1024 * 1024),
        max_report_bytes=_int("DD_MAX_REPORT_BYTES", 64 * 1024 * 1024),
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
        report_ui_base=ui_base,
        bind_host=os.environ.get("DD_BIND_HOST", "127.0.0.1"),
        expected_core_commit=(BACKEND_DIR / "CORE_COMMIT").read_text().strip(),
        sandbox_max_open_files=_int("DD_SANDBOX_MAX_OPEN_FILES", 512),
        ai_base_url=ai_base,
        ai_model=os.environ.get("DD_AI_MODEL", "").strip(),
        ai_timeout_seconds=_int("DD_AI_TIMEOUT_SECONDS", 90),
        ai_max_output_tokens=_int("DD_AI_MAX_OUTPUT_TOKENS", 2500),
        ai_response_format=ai_format,
        ai_openrouter_privacy=_bool("DD_AI_OPENROUTER_DENY_DATA_COLLECTION", True),
    )
