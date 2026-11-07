# Backend procedure-output validation — review handoff

Base: `42326824d0776b2dacace6a6819f02397c3676b9`.
Local branch: `codex/backend-pivot-acceptance`.
Core pin unchanged: `421da26caf030ce230778ffbd07ee1f72bf71217`.

## Problem and change

The pipeline previously checked required columns but accepted malformed procedure
values (including a string DIFF_FLAG, non-string attribute values, empty normalized
paths, and contradictory segment decisions). Other bad identities failed only
later during comparison/storage, after work or files had already been produced.

`backend/dd_backend/pipeline.py` now calls the existing pinned core's
`validate_normalized`, `validate_comparison`, and `validate_segment` at stage
boundaries. Application identity, expected SOURCE, unique keys, required field
types and decision/diff consistency are checked before artifact writes.
Violations become `OUTPUT_SCHEMA_INVALID` with procedure context.
No new API contract, dependency, core pin or frontend change is introduced.
Procedures that relied on invalid/coercible output now fail explicitly.
This does not validate arbitrary business logic or aggregate-procedure output.

## Tests and actual results

- New regression file: `backend/tests/test_pipeline_output_validation.py`.
  Baseline: 12 invalid-output expectations failed, four valid cases passed.
  Fixed: all 16 passed. Positive cases run real core and real DuckDB materialization.
- Existing core snapshot suite: 52 passed.
- Combined QA contract run, including the 16 pipeline cases before moving them
  to backend/tests: 80 passed, 10 existing xfailed, no unexpected failures.
  Pipeline cases belong in backend/tests because they need backend dependencies.
- All 2,002 public participant pairs accepted by the same core validators:
  502 changed apps, 385 decision changes, 289,533 comparison rows (about 12 s).
  This was an in-memory normalization/comparison/segment validation run, not
  HTTP, the complete backend worker, or browser acceptance.
- Git whitespace check passed.

Environment: Windows, isolated Python 3.12.14, real VCS-installed core at the
pinned SHA, DuckDB 1.5.6, FastAPI 0.162.2, Pydantic 2.14.2, pytest 9.2.0,
HTTPX 0.28.1. No repository dependency files changed.

The in-process pipeline tests replace Linux-specific input opening and installed
VCS verification ONLY. They do not assert worker containment, Linux file safety,
server sessions, HTTP behavior or supervisor correctness. Core identity was
separately checked by the passing existing core-pin contract test.

## Pavel: Linux verification

In your existing installed QA/backend environment:

```bash
python -m pytest backend/tests/test_pipeline_output_validation.py -q
# Existing backend regression suite (backend's own environment/assets):
(cd backend && .venv/bin/python -m pytest -q)
# Additional strict real-HTTP pivot coverage, using the existing QA launcher:
BACKEND_DIR="$PWD/backend" scripts/run_http_suite.sh builtin-only tests/http/test_results_contract.py -k filtered_pivot_matches_application_attributes -q
```

Also rerun the existing full-dataset API acceptance script for the release head.
The added HTTP cases check filtered SOURCE and SOURCE+CHANGE_TYPE layouts,
distinct counts, cell/member pagination and run/revision identity against
independently reconstructed memberships from application cards. They have NOT
been executed against an HTTP backend here. Do not count them as passing yet.

## Remaining integration boundaries

Artur owns the Pivot UI 422 repair. This patch does not fix or claim to fix it.
No full Linux backend suite, real-browser E2E or deployment was performed here.
The ten existing xfails belong to core runner/MartAPI/HTML contracts; they are
not new failures introduced by this patch and are not counted as passing checks.
No commit, push, merge or deployment has been performed.


## Follow-up: PR7 parallel-session failure investigation

The parallel-session HTTP test predates this branch. Its detached threads wrote
into a shared dictionary and were joined for 300 seconds, even though dataset
registration/configuration precedes Api.wait's own 300-second deadline. A worker
exception or early join expiry could leave only a missing-result error and allow
background requests to survive the assertion.

The test now uses futures to propagate the real worker exception, asserts run
acceptance and terminal success, and closes each HTTP client in finally. HTTP
request deadlines and Api.wait's run deadline are unchanged; no timeout is
silently ignored and no server behavior is mocked.

Fresh Ubuntu 24.04/WSL verification:
- Before this correction: parallel-session case plus both new Pivot cases, 3 passed
  in 25.99 seconds. Pavel's 300-second failure was not reproduced locally.
- After correction: full results HTTP file, 12 passed and 1 existing xfailed in
  32.29 seconds. The xfail is test_summary_has_decision_directions (API-DISC-01),
  unrelated to concurrency and not counted as a pass.
- Separate unchanged PR8 commit 6000464: full backend suite 109 passed in 444.62
  seconds. An earlier targeted group had 7 passes and one follow-up-run TIMEOUT;
  the corresponding main test passed in isolation. This mixed evidence does not
  establish that load alone caused Pavel's failures or certify a combined release.

No production code or dependency versions were changed by this follow-up.
