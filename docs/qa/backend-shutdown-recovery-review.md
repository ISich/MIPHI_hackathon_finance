# Backend shutdown recovery — review handoff

> **Статус:** влито в `main` — PR #8 (`codex/backend-shutdown-recovery`): коммит 6000464; финальный `main` = 010f42a. Ниже — исходная handoff-заметка; фразы «no commit/push/merge» относятся к моменту её написания.

Branch: `codex/backend-shutdown-recovery`, based directly on main
`42326824d0776b2dacace6a6819f02397c3676b9`.
This is separate from validation commit `9cb959c`; it changes no pipeline validators,
frontend files, HTTP contracts, dependency versions or deployment settings.

## Reproduced defect

The Linux graceful-shutdown regression failed on both main and the earlier
validation branch: expected FAILED/RUN_INTERRUPTED, but got RUNNING and
EXECUTION_UNCONTAINED. A newly exec'd supervisor could receive a termination
signal before its Python handlers were installed. It exited without a containment
marker, while recovery had already recorded its PID, leaving the queue blocked.

Three real-subprocess early-signal tests reproduced premature exits on main:
SIGTERM -> -15, SIGINT -> -2, SIGHUP -> -1. No user-code doubles were substituted.

## Fix

- Worker blocks TERM/INT/HUP in its launching thread around Popen, letting the
  supervisor inherit the mask across exec. The caller's original mask is restored
  in a finally block. No preexec_fn is introduced.
- Supervisor installs its stop handlers before unblocking these signals.
- A pending stop prevents user-code launch. The supervisor still runs containment
  and writes its marker only after successful verification.
- Existing fail-closed recovery, ownership fencing and forced-kill fallback remain.
  No marker is fabricated and no manual release command is used.

Files: backend/dd_backend/worker.py, backend/dd_backend/supervisor.py,
backend/tests/test_supervisor_startup.py, this review note.

## Verification

Ubuntu 24.04 / WSL2, Python 3.12.3, backend/requirements.lock, core 421da26.
The three early-signal regressions plus the previously failing shutdown test
passed after the fix (4 passed). An additional integration test verifies that a
queued second run completes after the interrupted run is failed on shutdown.
Full shutdown-only backend suite: **109 passed**, zero failures, one existing
Starlette/httpx deprecation warning; 426.18 seconds. This is 105 existing tests
plus four new cases, without the earlier validation commit.

Temporary combined verification (validation commit 9cb959c plus this fix):
**21 focused cases passed** (16 validation, four new supervisor/recovery, one
original shutdown test). The two strict real-backend HTTP Pivot cases also
passed. No combined Git merge or source commit was created. The shutdown-only
files were restored automatically after combined testing.
Combined full-dataset API acceptance also passed: 2,002 pairs, 502 changed
applications, 385 decision changes, 289,533 comparison rows, complete checks,
API=CLI, acceptance_problems=[]. Accept-to-final wall time: 48.758 s;
pipeline time: 42.013 s. These are measurements on this WSL host, not guarantees.
See the separate review package for full-run JSON and logs.

```bash
cd backend
.venv/bin/python -m pytest tests/test_supervisor_startup.py tests/test_d_execution.py::test_graceful_shutdown_fails_running_job_explicitly -q
.venv/bin/python -m pytest -q
```

Review the inherited signal-mask lifecycle, pending-stop handling and preservation
of fail-closed containment. No claim is made that this creates a filesystem/network
sandbox. UI Pivot 422 and browser acceptance remain Artur's/integration work.
This branch alone does not include the earlier procedure-output validation fix.
No commit/push/merge/deploy is performed by this handoff.
