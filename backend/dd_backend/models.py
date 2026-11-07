"""Pydantic wire models (request bodies are strict; responses document the contract)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
Stage = Literal["VALIDATING", "NORMALIZING", "COMPARING", "AGGREGATING", "CHECKING", "FINALIZING"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any]
    request_id: str


# ------------------------------------------------------------------ requests
class LoginRequest(Strict):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256, repr=False)


class AccountUser(BaseModel):
    username: str
    display_name: str


class Session(BaseModel):
    authenticated: bool
    kind: Literal["account", "anonymous-session"]
    user: AccountUser | None
    cookie_secure: bool
    execution_mode: str


class DatasetCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    root: str = Field(description="Name of a server-side allowlisted data root (see GET /api/datasets/roots)")
    mode: Literal["files", "dirs"] = Field(description="files: one BEFORE/AFTER JSON pair; dirs: two directories paired by file name")
    before: str = Field(description="Path relative to the root (no absolute paths, no '..')")
    after: str


class ScriptCreate(Strict):
    kind: Literal["normalize", "compare", "segments", "aggregate", "check"]
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(description="Python source (workspace editor text)")
    params: dict[str, Any] = Field(default_factory=dict)


class ScriptUpdate(Strict):
    code: Optional[str] = None
    params: Optional[dict[str, Any]] = None


class SlotRef(Strict):
    script_id: Optional[str] = Field(default=None, description="Omit to use the built-in procedure for this slot")
    params: Optional[dict[str, Any]] = None


class CheckRef(Strict):
    script_id: str
    params: Optional[dict[str, Any]] = None


class ConfigurationCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    dataset_id: str
    slots: dict[Literal["normalize", "compare", "segments", "aggregate"], SlotRef] = Field(default_factory=dict)
    checks: Optional[list[CheckRef]] = Field(
        default=None, description="Selected checks. Omitted = all built-in organizer checks; [] = explicitly none "
                                  "(technical run; report completeness NO_CHECKS_SELECTED)")


class RunCreate(Strict):
    configuration_id: str


class CheckRunCreate(Strict):
    checks: list[CheckRef]


class PivotDrillDown(Strict):
    group: dict[str, Any] = Field(description="pivot_facts dimensions incl. SOURCE (D4 ReportService.group_members)")
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class PivotQuery(Strict):
    dimensions: list[str] = Field(description="BaseFacts dimensions to group by (D4 BASE_DIMS whitelist)")
    filters: dict[str, Any] = Field(default_factory=dict, description="dimension -> value | [values] | null")
    limit: int = Field(default=100, description="1..500 (validated by D4)")
    offset: int = Field(default=0)


# ----------------------------------------------------------------- responses
class Health(BaseModel):
    status: str


class DatasetRevision(BaseModel):
    revision_id: str
    fingerprint: str
    pairs: int
    missing_before: list[str]
    missing_after: list[str]
    created_at: str


class Dataset(BaseModel):
    dataset_id: str
    name: str
    shared: bool
    root: str
    mode: str
    before: str
    after: str
    created_at: str
    revisions: list[DatasetRevision]


class DataRoots(BaseModel):
    roots: list[str]


class DatasetTable(BaseModel):
    dataset_id: str
    side: Literal["before", "after"]
    columns: list[str]
    rows: list[list[str | int | float | bool | None]]


class Script(BaseModel):
    script_id: str
    kind: str
    source: Literal["builtin", "workspace", "file"]
    name: str
    filename: Optional[str]
    builtin_ref: Optional[str]
    shared: bool
    params: dict[str, Any]
    revision: int
    code_sha256: str
    created_at: str
    updated_at: str
    declared_params: Optional[dict[str, Any]] = Field(
        default=None, description="check: CHECK.params read statically (AST, not executed); builtin normalize: presets")
    code: Optional[str] = None


class ScriptKind(BaseModel):
    kind: str
    entrypoint: str
    output_columns: list[str]
    template: str
    example: str
    sources: list[str]
    custom_execution_enabled: bool


class Configuration(BaseModel):
    config_id: str
    name: str
    dataset_id: str
    slots: dict[str, Any]
    checks: list[Any]
    created_at: str


class RunError(BaseModel):
    code: str
    message: Optional[str]


class Run(BaseModel):
    run_id: str
    status: Status
    stage: Optional[Stage]
    substep: Optional[str]
    processed: Optional[int]
    total: Optional[int]
    config_id: str
    dataset_id: str
    dataset_revision_id: str
    initial_check_run_id: str
    initial_report_id: str
    report_status: Optional[str]
    checks_completeness: Optional[str]
    error: Optional[RunError]
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    links: dict[str, str]


class RunPage(BaseModel):
    items: list[Run]
    total: int
    limit: int
    offset: int


class Event(BaseModel):
    seq: int
    ts: str
    check_run_id: Optional[str]
    stage: Optional[str]
    substep: Optional[str]
    level: str
    message: str
    processed: Optional[int]
    total: Optional[int]
    code_ref: Optional[str]


class EventPage(BaseModel):
    items: list[Event]
    next_after: int


class CodeSnapshot(BaseModel):
    run_id: str
    slot: str
    script_id: str
    kind: str
    source: str
    name: str
    script_revision: int
    code_sha256: str
    params: dict[str, Any]
    code: str
    check_run_id: Optional[str] = None


class Artifact(BaseModel):
    artifact_id: str
    kind: str
    rows: Optional[int]
    bytes: int
    sha256: str
    created_at: str
    download: str


class ArtifactList(BaseModel):
    run_id: str
    items: list[Artifact]


class Execution(BaseModel):
    execution_id: str
    slot: str
    script_id: str
    check_id: Optional[str]
    label: Optional[str]
    params: dict[str, Any]
    execution_status: Literal["SUCCEEDED", "ERROR", "TIMEOUT", "INVALID_OUTPUT", "IMPORT_ERROR", "CONTRACT_ERROR", "DUPLICATE_ID"]
    rows_count: int
    diagnostics: list[dict[str, Any]]
    duration_seconds: Optional[float]


class CheckRun(BaseModel):
    check_run_id: str
    run_id: str
    dataset_revision_id: str
    report_id: str
    initial: bool
    status: Status
    selected: list[dict[str, Any]]
    executions: list[Execution]
    error: Optional[RunError]
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    links: dict[str, str]


class Report(BaseModel):
    report_id: str
    run_id: str
    dataset_revision_id: str
    check_run_id: str
    status: Literal["PENDING", "PUBLISHED", "FAILED"]
    completeness: Optional[Literal["COMPLETE", "INCOMPLETE", "NO_CHECKS_SELECTED"]]
    sha256: Optional[str]
    created_at: str
    published_at: Optional[str]
    links: dict[str, str]


class ReportList(BaseModel):
    run_id: str
    initial_report_id: str
    items: list[Report]


class ReportChecks(BaseModel):
    report_id: str
    run_id: str
    check_run_id: str
    dataset_revision_id: str
    completeness: str
    summary: dict[str, Any]
    checks: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    timings_seconds: dict[str, Any]
    executions: list[dict[str, Any]]


class Readiness(BaseModel):
    ready: bool
    checks: list[dict[str, Any]]
    execution_mode: str
    warnings: list[str]
