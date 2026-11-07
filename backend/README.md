# D2 backend — API, registry, single worker, run storage

Platform runtime for the hackathon "СПР change analysis" project. It does **not** contain the
normalizer/comparator/MartAPI/checks/HTML layout: those come unchanged from the D1/D4 core package
`decision_diff` (branch `SomeShit`), pinned by commit in [`CORE_COMMIT`](CORE_COMMIT) and
[`requirements.txt`](requirements.txt).

Stack: Python ≥ 3.11 (verified on **3.12.3**), FastAPI + Pydantic + Uvicorn, SQLite (WAL) for metadata,
immutable per-run artifact directories, per-run DuckDB mart built by D4 `decision_diff.storage`.
No Redis/Celery/containers.

## Prerequisites

- Python 3.11+ with `venv`; `git`; Git access to the private repo `ISich/MIPHI_hackathon_finance`
  (your normal Git credential helper is used by `pip` and `fetch_core.sh`).
- Linux/macOS (worker uses POSIX process groups and rlimits; `PR_SET_PDEATHSIG` on Linux only).

## Install (clean checkout)

```bash
cd backend
python3 -m venv .venv                     # if ensurepip is missing: python3 -m venv --without-pip .venv
                                           #   && curl -sSo /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
                                           #   && .venv/bin/python /tmp/get-pip.py
.venv/bin/python -m pip install -r requirements-dev.txt -e .   # exact versions: requirements.lock
# after changing CORE_COMMIT: .venv/bin/python -m pip install --force-reinstall --no-deps -r requirements.txt
scripts/fetch_core.sh                      # read-only checks/, examples/, tests/ of the pinned core commit -> .core/<sha>/
```

`fetch_core.sh` uses `git archive` of the pinned commit from this repo's `origin`; nothing is copied into
Git. The pinned core package itself is installed by pip from the same commit; `/ready` verifies that the
installed commit equals `CORE_COMMIT`.

## Run

**One process (default):** API + embedded worker thread (the thread only orchestrates child processes):

```bash
.venv/bin/python -m dd_backend serve --host 127.0.0.1 --port 8000
```

**Two processes (optional):** API without worker + standalone worker:

```bash
DD_EMBEDDED_WORKER=0 .venv/bin/python -m dd_backend serve --host 127.0.0.1 --port 8000
.venv/bin/python -m dd_backend worker
```

At most one job (data run or check run) executes at a time across all workers (claimed in SQLite under
`BEGIN IMMEDIATE`). Stop with Ctrl-C / SIGTERM: a job running at shutdown is marked `FAILED` /
`RUN_INTERRUPTED`; queued jobs are kept and executed after the next start.

By default `DD_DATA_ROOTS` allows the core fixtures as root `examples`. Register the real fixture as a
shared dataset (operator CLI; HTTP clients can also `POST /api/datasets` inside allowlisted roots):

```bash
.venv/bin/python -m dd_backend register-dataset --name "core fixture" --root examples --mode files \
    --before I32554354_other.json --after I32554354.json
```

Full open dataset (not in this repo; put it under an allowlisted root, e.g. `DD_DATA_ROOTS=examples=...,data=/path/to/data`):

```bash
.venv/bin/python -m dd_backend register-dataset --name "RUN-20260827-0001" --root data --mode dirs \
    --before RUN-20260827-0001/RESULTS/BEFORE_MASTER --after RUN-20260827-0001/RESULTS/AFTER_BETA
```

## Smoke and tests

```bash
scripts/smoke.sh /tmp/dd-smoke          # real uvicorn on 127.0.0.1:<random>, full run + check-only run via curl
.venv/bin/python -m pytest -q           # backend tests (real core, real D4 mart, real subprocess worker)
(cd .core/$(cat CORE_COMMIT) && ../../.venv/bin/python -m pytest -q tests)   # core tests on the pinned package
.venv/bin/python -m dd_backend export-openapi --out openapi.json            # regenerate; a test fails if stale
```

Real request/response examples captured by the smoke script: [`docs/examples/`](docs/examples/).

Minimal curl session (cookie jar = one owner):

```bash
B=http://127.0.0.1:8000; J=/tmp/dd.cookies
curl -s -c $J -b $J $B/api/datasets                                   # first /api call issues the dd_session cookie
curl -s -c $J -b $J -H 'content-type: application/json' \
     -d '{"name":"demo","dataset_id":"<ds_id>"}' $B/api/configurations   # all built-in procedures + 5 checks
curl -s -c $J -b $J -H 'content-type: application/json' -H 'Idempotency-Key: 1' \
     -d '{"configuration_id":"<config_id>"}' $B/api/runs                  # 202 + run_id
curl -s -b $J $B/api/runs/<run_id>                                      # status/stage/processed/total
curl -s -b $J "$B/api/runs/<run_id>/events?after=0"
curl -s -b $J $B/api/runs/<run_id>/summary                              # 409 NOT_READY until COMPLETED
curl -s -b $J $B/api/runs/<run_id>/checks                               # initial report
```
Machine-readable schema for the frontend: [`openapi.json`](openapi.json) (also served at `/openapi.json`).

## Environment variables (no secrets are needed or read)

| Variable | Default | Meaning |
|---|---|---|
| `DD_HOME` | `backend/var` | SQLite DB, run directories, stored scripts |
| `DD_DATA_ROOTS` | `examples=.core/<sha>/examples` | `name=path,...` allowlisted dataset roots |
| `DD_CHECKS_DIR` | `.core/<sha>/checks` | built-in organizer checks (registered read-only) |
| `DD_EXECUTION_MODE` | `builtin-only` | `builtin-only` or `trusted-local` (custom Python; loopback only) |
| `DD_EMBEDDED_WORKER` | `1` | `0` = run `python -m dd_backend worker` separately |
| `DD_RUN_TIMEOUT_SECONDS` | `900` | wall clock per data-run pipeline child |
| `DD_CHECK_TIMEOUT_SECONDS` | `120` | wall clock per check child |
| `DD_MAX_CODE_BYTES` | `262144` | max script size (editor or upload) |
| `DD_MAX_OUTPUT_BYTES` | `4 GiB` | per-file limit (RLIMIT_FSIZE) and total artifacts per run |
| `DD_MAX_LOG_BYTES` | `1 MiB` | captured stdout/stderr per child |
| `DD_MAX_MEMORY_MB` | `6144` | RLIMIT_AS per child |
| `DD_WORKER_LEASE_SECONDS` | `15` | heartbeat lease for worker liveness / interrupted-job detection |
| `DD_COOKIE_SECURE` | `0` | set `1` behind TLS (local HTTP mode otherwise) |
| `DD_ALLOWED_HOSTS` | `127.0.0.1,localhost,::1` | accepted `Host` names (anti DNS-rebinding); other hosts → 400. trusted-local accepts loopback names only |
| `DD_ALLOWED_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | extra origins allowed for POST/PUT (same-origin always allowed; foreign Origin / `Sec-Fetch-Site: cross-site` → 403) |
| `DD_REPORT_UI_BASE` | `http://127.0.0.1:5173` | absolute UI base embedded in HTML reports (provisional route `/runs/{run}/reports/{report}`) |

## API overview

Envelope for every error: `{code, message, details, request_id}`; `x-request-id` header on every response.
Codes: 202 accepted run/check-run · 400 `IDEMPOTENCY_KEY_REQUIRED` · 403 `CUSTOM_EXECUTION_DISABLED` /
read-only · 404 `NOT_FOUND` (also for other owners' IDs — existence is not leaked) · 409 `NOT_READY` /
`IDEMPOTENCY_KEY_REUSED` · 413 · 422 `VALIDATION_ERROR` and specific dataset/script codes · 501
`ANALYTICS_UNAVAILABLE` · 503 `/ready` not ready.

- `POST /api/runs` requires `Idempotency-Key`; same key + same body (per session owner) returns the same run
  with `Idempotent-Replay: true`; same key + other body → 409. Same for `POST /api/runs/{id}/check-runs`.
- Run `status` (QUEUED/RUNNING/COMPLETED/FAILED) is separate from `stage`
  (VALIDATING → NORMALIZING → COMPARING [substep SEGMENTS] → AGGREGATING → CHECKING → FINALIZING).
  `processed/total` are only set where the pipeline really counts pairs.
- Code/params are snapshotted when the run is **accepted**; `GET /api/runs/{id}/code/{slot}` returns the
  executed snapshot. Editing a script later only affects new runs.
- Each data run creates `initial_check_run_id`/`initial_report_id`; `GET /runs/{id}/checks` always reads
  that report. `POST /runs/{id}/check-runs` makes a new check run + report on the same data revision.
- Report `completeness`: `COMPLETE` | `INCOMPLETE` (some check had an execution problem) |
  `NO_CHECKS_SELECTED` (technical run, not acceptance of the five checks).
- Built-in normalize params: `{"config": "real"|"teaching", "excluded_paths": [...], "arrays": {path: {mode, keys, scalar_suffix}}}`;
  `excluded_paths`/`arrays` replace the preset's lists (presets are visible in `declared_params` of the built-in
  normalize script). The pinned core `NormalizationConfig` is built from them; the normalizer itself is unchanged.
  Check scripts expose `declared_params` = `CHECK.params` read statically (AST), never by executing the file.
- Check `execution_status`: `SUCCEEDED` (0..N rows) | `ERROR` | `TIMEOUT` | `INVALID_OUTPUT` |
  `IMPORT_ERROR` | `CONTRACT_ERROR` | `DUPLICATE_ID`. Business `RESULT` stays PASS/FAIL only.

## Security model — read before exposing anything

- **Default `builtin-only`:** only the pinned core procedures and the organizer checks execute. Creating a
  run/check-run that references workspace/file code returns 403 `CUSTOM_EXECUTION_DISABLED`; nothing runs.
- **`trusted-local` (opt-in):** user Python runs in a child process with a scrubbed environment, own process
  group, rlimits, timeouts and capped logs. This is **not** a filesystem or network sandbox: the code has the
  server user's file and network rights. `serve` refuses this mode on non-loopback hosts. Do not publish it.
- Sessions are anonymous, server-side (random 256-bit cookie, stored hashed, HttpOnly, SameSite=Lax). Not IAM.
- Dataset paths are names of allowlisted roots + relative paths; absolute paths, `..` and symlinks resolving
  outside the root are rejected. Server paths never appear in responses; child diagnostics are path-sanitized.
- `serve` refuses non-loopback binds unless `--allow-non-loopback` is given (deployment is the operator's call);
  behind a proxy also set `DD_ALLOWED_HOSTS` to the public name. The app itself (also when started directly via
  uvicorn) rejects unknown `Host` headers, cross-origin state-changing requests and, in trusted-local, any
  non-loopback client address.
- Request bodies are limited while being received (2 MiB JSON, code limit + 64 KiB multipart), also without
  `Content-Length`.
- Worker: a job is failed as interrupted only when its worker process is gone (same host: pid + start time);
  every write of a worker is fenced by job ownership. The whole child process group is killed after each child.
  Inputs are read once (no symlink, real path inside the root), and the fingerprinted bytes are the ones parsed.
  A run refuses to execute when the installed core differs from the accepted snapshot (`CORE_VERSION_MISMATCH`).

## Analytics (D4 ports of the pinned core)

- AGGREGATING calls `decision_diff.base_facts.materialize_base_facts` once on the run's own DuckDB (single
  writer) and `ReportService.validate_memberships`; a mismatch fails the run (`BASE_FACTS_INVALID`).
- `POST /api/runs/{id}/pivot` `{dimensions, filters, limit<=500, offset}` → `PivotRollup.cells`: distinct
  APP_ID counts from BaseMembership, `total` = number of cells, a signed `group_locator` per cell (HMAC key
  generated by the server in `$DD_HOME/pivot-locator.key`, bound to run + data revision).
- `GET /api/runs/{id}/groups/{locator}/applications` → `PivotRollup.members`: page + full distinct total.
- `GET /api/runs/{id}/pivot-facts` and `POST /api/runs/{id}/pivot-facts/applications` → `ReportService`
  (pages with `total`, limit ≤ 500). Unknown dimensions/filters/paging → 422 `PIVOT_QUERY_INVALID`.
- Runs produced before BaseFacts existed answer 409 `ANALYTICS_UNAVAILABLE` for pivot.

## Known gaps
- No resume of interrupted runs (they are failed deterministically); no cancel endpoint.
- Run directories are kept until removed manually (`$DD_HOME/runs/<run_id>`).
