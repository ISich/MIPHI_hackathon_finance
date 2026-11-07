# UI pivot contract acceptance — 2026-11-07

Branch: `codex/ui-pivot-contract`, created directly from freshly fetched main
`42326824d0776b2dacace6a6819f02397c3676b9`. No old UI branch merged.
Backend source, execution policy and deployment configuration are unchanged.

## Contract evidence

`backend/openapi.json`: POST `/api/runs/{run_id}/pivot` binds `PivotQuery`;
requires `dimensions`, accepts object `filters`, optional `limit/offset`, forbids extras.
UI maps row/column axes into unique dimensions; report context stays in navigation.
`backend/dd_backend/api.py:296` delegates to pinned D4 `PivotRollup.cells`.
Pinned core `421da26caf030ce230778ffbd07ee1f72bf71217`,
`decision_diff/pivot_rollup.py`: response contains `items` with dimensions,
cnt, group_locator, plus total/limit/offset and run/data revision.
No row/column/grand totals are returned; counts are never summed in the UI.

GET `/api/runs/{run_id}/groups/{group}/applications` is present in OpenAPI
and implemented at `backend/dd_backend/api.py:309` via `PivotRollup.members`.
The client already used that route; returned locators now travel unchanged to it.
Route/source alignment VERIFIED; successful live drill-down NOT VERIFIED.

## Changes for review

- Real wire types, request adapter, sparse rows × columns mapping, page controls,
  all pinned BASE_DIMS in the attribute selector (including CHANGE_TYPE).
- Current wire contract in default mock; obsolete payload returns 422.
- 4xx remain visible errors with HTTP status, details and request id.
  Only HTTP 501 uses the compatibility fallback.
- Terminal Run pages continue polling journal/report list; report selection
  remains explicit. Late report links appear in monitor without reload.
- Real E2E requires a successful pivot response and checks request/count/locator;
  added real test for a later builtin CheckRun in an open terminal monitor.

## Commands and actual results

Run from `frontend/`, 2026-11-07 around 20:39–20:47 MSK:

- `npm run build`: PASS (vue-tsc + Vite production build).
- `npm test`: 67 tests PASS, including adapter, sparse/null/empty coordinates,
  page/reset behavior, 422 UX and late CheckRun events/report regression.
- `npm run check:openapi -- ../backend/openapi.json`: PASS.
- `npm run e2e:mock -- --project=desktop`: 7 passed, exit 0.
  Five application smoke tests plus two existing error-guard meta-tests;
  the meta-tests intentionally provoke failures and are marked test.fail.
  This is synthetic UI evidence, not real backend E2E.
- `npm run e2e:mock`: exit 0, 13 passed + 1 flaky (narrow first smoke
  timed out while source edits triggered dev updates; passed on retry).
- `npm run e2e:mock -- --project=narrow --retries=0`: 7 passed, exit 0,
  clean rerun after source edits. No application smoke is skipped or xfailed.
- `npm run e2e:real -- --project=desktop --grep 'configuration → Run' --timeout=15000 --retries=0`:
  FAILED (1 test). Browser guard recorded HTTP 500 GET `/api/session`;
  Vite proxy reported ECONNREFUSED 127.0.0.1:8000. Run was never created.
- `curl -sS --max-time 3 http://127.0.0.1:8000/ready`: exit 7, connection refused.
- `git diff --check`: PASS.

The local machine is macOS; backend worker requires Linux containment.
No Linux runtime/backend endpoint was available. A backend endpoint was requested
from the owner. No worker containment or execution policy was bypassed.
Native access to the existing Warp terminal monitor was denied by the computer
tool; no alternative access to that window was attempted.

## Nine demo steps

| Step | Available evidence | Real backend status |
| --- | --- | --- |
| 1. config/source/procedure/start (3 min) | mock browser smoke | BLOCKED: backend absent |
| 2. stage/progress/journal (3 min) | mock browser + component regressions | BLOCKED; existing monitor access denied |
| 3. differing apps/decision (1 min) | mock browser summary | NOT VERIFIED |
| 4. arbitrary attributes/change types (3 min) | adapter/table tests; real E2E assertions added | NOT VERIFIED |
| 5. aggregate → applications → before/after (3 min) | mock browser smoke; route/core inspected | NOT VERIFIED |
| 6. checks verdicts/app links (2 min) | existing component + browser smoke | NOT VERIFIED |
| 7. new check → apply → report (2 min) | synthetic mock only | BLOCKED: no authorized isolated execution context |
| 8. HTML download/open/app-summary link (1 min) | existing links inspected; real E2E HTML assertion retained | NOT VERIFIED end to end |
| 9. architecture/stack (2 min) | Vue 3/TS/Vite client, same-origin FastAPI API, SQLite registry, subprocess worker, DuckDB/D4 distinct rollup | source inspected; demo timing NOT VERIFIED |

No real E2E GREEN, custom Python execution, push, merge or deploy claimed.
Before merge: independent review of the delivered exact head and successful
real backend acceptance are still required. StopCoding: 2026-11-08 09:30 MSK.
