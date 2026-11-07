"""HTTP routes (/api). Owner comes only from request.state.owner_id (server session)."""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import auth, models as m, sessions
from .errors import ApiError, not_found
from .registry import SCRIPT_KINDS
from .runs import RunService

router = APIRouter(prefix="/api")

ERRORS = {r: {"model": m.ErrorBody} for r in (400, 403, 404, 409, 413, 422)}


def _ctx(request: Request) -> tuple[str, Any, RunService]:
    app = request.app
    reg = app.state.registry
    svc = getattr(app.state, "runs", None)
    if svc is None:
        svc = app.state.runs = RunService(app.state.settings, app.state.db, reg)
    return request.state.owner_id, reg, svc


# ------------------------------------------------------------------ session
@router.get("/session", tags=["session"], response_model=m.Session,
            summary="Current account or anonymous session (cookie is issued automatically)")
def session(request: Request) -> dict:
    s = request.app.state.settings
    account = auth.user(request.app.state.db, request.state.owner_id)
    return {"authenticated": account is not None, "kind": "account" if account else "anonymous-session", "user": account,
            "cookie_secure": s.cookie_secure, "execution_mode": s.execution_mode}


def _rotate_session(request: Request, owner_id: str | None = None) -> None:
    old_token = request.state.new_session_token or request.cookies.get(sessions.COOKIE_NAME)
    token, owner = sessions.create(request.app.state.db, owner_id, revoke_token=old_token)
    request.state.new_session_token = token
    request.state.owner_id = owner


@router.post("/auth/login", tags=["session"], response_model=m.Session,
             responses={**ERRORS, 401: {"model": m.ErrorBody}, 429: {"model": m.ErrorBody}})
def login(body: m.LoginRequest, request: Request):
    owner = auth.authenticate(request.app.state.db, body.username, body.password)
    _rotate_session(request, owner)
    return session(request)


@router.post("/auth/logout", tags=["session"], response_model=m.Session)
def logout(request: Request):
    _rotate_session(request)
    return session(request)


# ----------------------------------------------------------------- datasets
@router.get("/datasets/roots", tags=["datasets"], response_model=m.DataRoots)
def data_roots(request: Request):
    return {"roots": sorted(request.app.state.settings.data_roots)}


@router.get("/datasets", tags=["datasets"], response_model=list[m.Dataset])
def list_datasets(request: Request):
    owner, reg, _ = _ctx(request)
    return reg.list_datasets(owner)


@router.post("/datasets", tags=["datasets"], status_code=201, response_model=m.Dataset, responses=ERRORS)
def create_dataset(body: m.DatasetCreate, request: Request):
    owner, reg, _ = _ctx(request)
    return reg.create_dataset(owner, body.name, body.root, body.mode, body.before, body.after)


@router.get("/datasets/{dataset_id}", tags=["datasets"], response_model=m.Dataset, responses=ERRORS)
def get_dataset(dataset_id: str, request: Request):
    owner, reg, _ = _ctx(request)
    return reg.get_dataset(owner, dataset_id)


@router.post("/datasets/{dataset_id}/revisions", tags=["datasets"], response_model=m.Dataset, responses=ERRORS,
             summary="Rescan files; adds a new revision if the fingerprint changed")
def rescan_dataset(dataset_id: str, request: Request):
    owner, reg, _ = _ctx(request)
    ds = reg.get_dataset(owner, dataset_id)
    if ds["shared"]:
        raise ApiError(403, "DATASET_READ_ONLY", "Shared datasets are rescanned by the operator CLI")
    return reg.rescan_dataset(owner, dataset_id)


# ------------------------------------------------------------------ scripts
@router.get("/script-kinds", tags=["scripts"], response_model=list[m.ScriptKind])
def script_kinds(request: Request):
    enabled = request.app.state.settings.execution_mode == "trusted-local"
    return [{"kind": k, **v, "sources": ["builtin", "workspace", "file"], "custom_execution_enabled": enabled}
            for k, v in SCRIPT_KINDS.items()]


@router.get("/scripts", tags=["scripts"], response_model=list[m.Script])
def list_scripts(request: Request, kind: Optional[str] = None):
    owner, reg, _ = _ctx(request)
    return reg.list_scripts(owner, kind)


@router.post("/scripts", tags=["scripts"], status_code=201, response_model=m.Script, responses=ERRORS,
             summary="Create a workspace script from editor text")
def create_script(body: m.ScriptCreate, request: Request):
    owner, reg, _ = _ctx(request)
    return reg.create_script(owner, body.kind, "workspace", body.name, body.code.encode(), body.params)


async def _read_upload(request: Request, file: UploadFile) -> bytes:
    limit = request.app.state.settings.max_code_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "CODE_TOO_LARGE", "Uploaded file exceeds the size limit", {"limit_bytes": limit})
    return data


def _params(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "params must be a JSON object")
    if not isinstance(value, dict):
        raise ApiError(422, "VALIDATION_ERROR", "params must be a JSON object")
    return value


@router.post("/scripts/upload", tags=["scripts"], status_code=201, response_model=m.Script, responses=ERRORS,
             summary="Create a script from an uploaded .py file (source=file)")
async def upload_script(request: Request, kind: str = Form(...), name: str = Form(...),
                        params: Optional[str] = Form(None), file: UploadFile = File(...)):
    owner, reg, _ = _ctx(request)
    data = await _read_upload(request, file)
    return reg.create_script(owner, kind, "file", name, data, _params(params), filename=file.filename)


@router.get("/scripts/{script_id}", tags=["scripts"], response_model=m.Script, responses=ERRORS)
def get_script(script_id: str, request: Request):
    owner, reg, _ = _ctx(request)
    return reg.get_script(owner, script_id)


@router.put("/scripts/{script_id}", tags=["scripts"], response_model=m.Script, responses=ERRORS,
            summary="Edit workspace text/params (new revision; runs already started keep their snapshot)")
def update_script(script_id: str, body: m.ScriptUpdate, request: Request):
    owner, reg, _ = _ctx(request)
    current = reg.get_script(owner, script_id, with_code=False)
    if current["source"] == "file" and body.code is not None:
        raise ApiError(422, "SCRIPT_SOURCE_MISMATCH", "File scripts are replaced via PUT /api/scripts/{id}/file")
    return reg.update_script(owner, script_id, body.code.encode() if body.code is not None else None, body.params)


@router.put("/scripts/{script_id}/file", tags=["scripts"], response_model=m.Script, responses=ERRORS)
async def replace_script_file(script_id: str, request: Request, file: UploadFile = File(...)):
    owner, reg, _ = _ctx(request)
    current = reg.get_script(owner, script_id, with_code=False)
    if current["source"] != "file":
        raise ApiError(422, "SCRIPT_SOURCE_MISMATCH", "Only file scripts accept an uploaded replacement")
    data = await _read_upload(request, file)
    return reg.update_script(owner, script_id, data, None, filename=file.filename)


# ----------------------------------------------------------- configurations
@router.get("/configurations", tags=["configurations"], response_model=list[m.Configuration])
def list_configurations(request: Request):
    owner, reg, _ = _ctx(request)
    return reg.list_configurations(owner)


@router.post("/configurations", tags=["configurations"], status_code=201, response_model=m.Configuration, responses=ERRORS)
def create_configuration(body: m.ConfigurationCreate, request: Request):
    owner, reg, _ = _ctx(request)
    slots = {k: v.model_dump() for k, v in body.slots.items()}
    checks = [c.model_dump() for c in body.checks] if body.checks is not None else None
    return reg.create_configuration(owner, body.name, body.dataset_id, slots, checks)


@router.get("/configurations/{config_id}", tags=["configurations"], response_model=m.Configuration, responses=ERRORS)
def get_configuration(config_id: str, request: Request):
    owner, reg, _ = _ctx(request)
    return reg.get_configuration(owner, config_id)


# --------------------------------------------------------------------- runs
IDEM_DOC = "Required. Same key + same body returns the already accepted resource (no duplicate); scope = session owner."


@router.post("/runs", tags=["runs"], status_code=202, response_model=m.Run, responses=ERRORS,
             summary="Accept a Run (snapshots code/params now); executed asynchronously by the worker")
def create_run(body: m.RunCreate, request: Request,
               idempotency_key: Optional[str] = Header(default=None, description=IDEM_DOC)):
    owner, _, svc = _ctx(request)
    run, replay = svc.create_run(owner, body.configuration_id, idempotency_key)
    return JSONResponse(status_code=202, content=run,
                        headers={"Location": run["links"]["self"], "Idempotent-Replay": "true" if replay else "false"})


@router.get("/runs", tags=["runs"], response_model=m.RunPage)
def list_runs(request: Request, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    owner, _, svc = _ctx(request)
    return svc.list_runs(owner, limit, offset)


@router.get("/runs/{run_id}", tags=["runs"], response_model=m.Run, responses=ERRORS)
def get_run(run_id: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.get_run(owner, run_id)


@router.get("/runs/{run_id}/events", tags=["runs"], response_model=m.EventPage, responses=ERRORS)
def run_events(run_id: str, request: Request, after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000)):
    owner, _, svc = _ctx(request)
    return svc.events(owner, run_id, after, limit)


@router.get("/runs/{run_id}/code/{slot}", tags=["runs"], response_model=m.CodeSnapshot, responses=ERRORS,
            summary="Code+params snapshot actually executed (slot: normalize|compare|segments|aggregate|check-NN)")
def run_code(run_id: str, slot: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.code(owner, run_id, slot)


@router.get("/runs/{run_id}/summary", tags=["results"], responses=ERRORS,
            summary="Computed summary of a COMPLETED run (409 NOT_READY before)")
def run_summary(run_id: str, request: Request) -> dict:
    owner, _, svc = _ctx(request)
    return svc.summary(owner, run_id)


@router.get("/runs/{run_id}/artifacts", tags=["results"], response_model=m.ArtifactList, responses=ERRORS)
def run_artifacts(run_id: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.artifacts(owner, run_id)


ARTIFACT_MEDIA = {".csv": "text/csv; charset=utf-8", ".json": "application/json", ".duckdb": "application/octet-stream"}
_BINARY = {"type": "string", "format": "binary"}


@router.get("/runs/{run_id}/artifacts/{artifact_id}", tags=["results"], response_class=FileResponse,
            responses={**ERRORS, 200: {"description": "Artifact file: CSV (';', UTF-8 BOM), summary JSON or DuckDB mart",
                                       "content": {"text/csv": {"schema": _BINARY},
                                                   "application/octet-stream": {"schema": _BINARY},
                                                   "application/json": {"schema": {"type": "object"}}}}})
def download_artifact(run_id: str, artifact_id: str, request: Request):
    owner, _, svc = _ctx(request)
    path, name = svc.artifact_file(owner, run_id, artifact_id)
    return FileResponse(path, filename=name, media_type=ARTIFACT_MEDIA.get(path.suffix, "application/octet-stream"))


# ------------------------------------------------- analytics via D4 DuckDBMart
def _mart(request: Request, run_id: str):
    owner, _, svc = _ctx(request)
    path = svc.mart_path(owner, run_id)
    from decision_diff.mart import DuckDBMart
    return DuckDBMart(path)


def _report_service(request: Request, run_id: str):
    owner, _, svc = _ctx(request)
    path = svc.mart_path(owner, run_id)
    from decision_diff.report_service import ReportService
    return ReportService(path)


def _query_error(exc: Exception) -> ApiError:
    return ApiError(422, "PIVOT_QUERY_INVALID", str(exc)[:300])


@router.get("/runs/{run_id}/pivot-facts", tags=["results"], responses=ERRORS,
            summary="Page of pivot facts with total (D4 ReportService.pivot_facts). CNT must not be summed across groups.")
def pivot_facts(run_id: str, request: Request, limit: int = Query(100), offset: int = Query(0)) -> dict:
    from decision_diff.report_service import ReportQueryError
    with _report_service(request, run_id) as reports:
        try:
            page = reports.pivot_facts(limit=limit, offset=offset)
        except ReportQueryError as exc:
            raise _query_error(exc)
    return {"run_id": run_id, **page, "next_offset": offset + limit if offset + limit < page["total"] else None}


@router.post("/runs/{run_id}/pivot-facts/applications", tags=["results"], responses=ERRORS,
             summary="Drill-down: distinct APP_IDs of a pivot_facts group with full total (D4 ReportService.group_members)")
def pivot_drill(run_id: str, body: m.PivotDrillDown, request: Request) -> dict:
    from decision_diff.report_service import ReportQueryError
    with _report_service(request, run_id) as reports:
        try:
            page = reports.group_members(body.group, limit=body.limit, offset=body.offset)
        except ReportQueryError as exc:
            raise _query_error(exc)
    return {"run_id": run_id, **page}


def _rollup(request: Request, run_id: str):
    import duckdb
    from decision_diff.pivot_rollup import PivotRollup
    owner, _, svc = _ctx(request)
    path = svc.mart_path(owner, run_id)          # owner check + NOT_READY before anything else
    run = svc.get_run(owner, run_id)
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con, PivotRollup(con, run_id=run_id, data_revision=run["dataset_revision_id"],
                                signing_secret=request.app.state.signing_key)
    except ValueError as exc:
        con.close()
        raise ApiError(409, "ANALYTICS_UNAVAILABLE",
                       "This run has no BaseFacts (produced by an older core); start a new run", {"reason": str(exc)[:200]})


@router.post("/runs/{run_id}/pivot", tags=["results"], responses=ERRORS,
             summary="Server pivot rollup over BaseFacts/BaseMembership (D4 PivotRollup.cells); distinct totals, signed group locators")
def pivot_rollup(run_id: str, body: m.PivotQuery, request: Request) -> dict:
    from decision_diff.pivot_rollup import PivotQueryError
    con, rollup = _rollup(request, run_id)
    try:
        return rollup.cells(dimensions=body.dimensions, filters=body.filters, limit=body.limit, offset=body.offset)
    except PivotQueryError as exc:
        raise _query_error(exc)
    finally:
        con.close()


@router.get("/runs/{run_id}/groups/{group}/applications", tags=["results"], responses=ERRORS,
            summary="APP_ID page + full distinct total of a pivot cell (D4 PivotRollup.members; locator bound to run/revision)")
def group_applications(run_id: str, group: str, request: Request, limit: int = Query(50), offset: int = Query(0)) -> dict:
    from decision_diff.pivot_rollup import PivotQueryError
    con, rollup = _rollup(request, run_id)
    try:
        return rollup.members(group, limit=limit, offset=offset)
    except PivotQueryError as exc:
        raise _query_error(exc)
    finally:
        con.close()


@router.get("/runs/{run_id}/applications/{app_id}", tags=["results"], responses=ERRORS,
            summary="Segment row and comparison attributes of one application (D4 DuckDBMart.application)")
def application(run_id: str, app_id: str, request: Request) -> dict:
    with _mart(request, run_id) as mart:
        try:
            return {"run_id": run_id, **mart.application(app_id)}
        except KeyError:
            raise not_found("application", app_id)


# --------------------------------------------------------- checks / reports
@router.get("/runs/{run_id}/checks", tags=["reports"], response_model=m.ReportChecks, responses=ERRORS,
            summary="Checks of the run's INITIAL report (never the latest)")
def run_checks(run_id: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.report_document(owner, svc.initial_report_id(owner, run_id))


@router.get("/runs/{run_id}/reports", tags=["reports"], response_model=m.ReportList, responses=ERRORS)
def run_reports(run_id: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.list_reports(owner, run_id)


@router.post("/runs/{run_id}/check-runs", tags=["reports"], status_code=202, response_model=m.CheckRun, responses=ERRORS,
             summary="Check-only execution on the finished data revision; creates new check_run_id + report_id")
def create_check_run(run_id: str, body: m.CheckRunCreate, request: Request,
                     idempotency_key: Optional[str] = Header(default=None, description=IDEM_DOC)):
    owner, _, svc = _ctx(request)
    cr, replay = svc.create_check_run(owner, run_id, [c.model_dump() for c in body.checks], idempotency_key)
    return JSONResponse(status_code=202, content=cr,
                        headers={"Location": cr["links"]["self"], "Idempotent-Replay": "true" if replay else "false"})


@router.get("/check-runs/{check_run_id}", tags=["reports"], response_model=m.CheckRun, responses=ERRORS)
def get_check_run(check_run_id: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.get_check_run(owner, check_run_id)


@router.get("/check-runs/{check_run_id}/code/{slot}", tags=["reports"], response_model=m.CodeSnapshot, responses=ERRORS)
def check_run_code(check_run_id: str, slot: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.check_run_code(owner, check_run_id, slot)


@router.get("/reports/{report_id}", tags=["reports"], response_model=m.Report, responses=ERRORS)
def get_report(report_id: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.get_report(owner, report_id)


@router.get("/reports/{report_id}/checks", tags=["reports"], response_model=m.ReportChecks, responses=ERRORS)
def report_checks(report_id: str, request: Request):
    owner, _, svc = _ctx(request)
    return svc.report_document(owner, report_id)


@router.get("/reports/{report_id}/checks.html", tags=["reports"], response_class=HTMLResponse, responses=ERRORS,
            summary="HTML snapshot rendered by D4 decision_diff.html_report for this exact report")
def report_html(report_id: str, request: Request):
    owner, _, svc = _ctx(request)
    doc = svc.report_document(owner, report_id)
    from decision_diff.html_report import render_html_report
    base = request.app.state.settings.report_ui_base.rstrip("/")
    html = render_html_report(doc, report_url=f"{base}/runs/{doc['run_id']}/reports/{report_id}")
    return HTMLResponse(html, headers={"Content-Disposition": f'inline; filename="{report_id}.html"',
                                       "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
