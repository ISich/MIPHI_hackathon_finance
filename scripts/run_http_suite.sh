#!/usr/bin/env bash
# Start the backend (from BACKEND_DIR, read-only) on 127.0.0.1 with a throw-away DD_HOME,
# run the black-box HTTP tests against it, then stop only the process started here.
#
#   BACKEND_DIR=~/projects/MIPHI_hackathon_finance/backend scripts/run_http_suite.sh [builtin-only|trusted-local] [pytest args/paths]
# Without pytest args the whole tests/http suite runs. Run from the repository root.
#
# Nothing is written into BACKEND_DIR (PYTHONDONTWRITEBYTECODE=1, cwd and DD_HOME elsewhere).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-builtin-only}"; shift || true
BACKEND_DIR="${BACKEND_DIR:?set BACKEND_DIR to the backend checkout (contains dd_backend/)}"
# Resolve every user-supplied path NOW: the server is started from a temporary cwd (CR #1).
BACKEND_DIR="$(cd "$BACKEND_DIR" && pwd)"
BACKEND_PY="$(realpath -s "${BACKEND_PY:-$BACKEND_DIR/.venv/bin/python}")"
PORT="${QA_PORT:-18765}"
QA_PY="$(realpath -s "${QA_PY:-$ROOT/.venv/bin/python}")"
[ -x "$BACKEND_PY" ] || { echo "backend python not found: $BACKEND_PY" >&2; exit 2; }
case "$MODE" in builtin-only|trusted-local) ;; *) echo "unknown mode $MODE" >&2; exit 2;; esac
# Refuse a busy port: otherwise an unrelated server could answer /health and be tested instead (CR #2).
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  echo "port $PORT on 127.0.0.1 is already in use; refusing to test an unknown server (set QA_PORT)" >&2; exit 3
fi
WORK="$(mktemp -d "${TMPDIR:-/tmp}/qa-http-XXXXXX")"
CHECKS_DIR="$("$ROOT/scripts/fetch_core_checks.sh")"
EXAMPLES_DIR="$(dirname "$CHECKS_DIR")/examples"
"$QA_PY" "$ROOT/scripts/make_http_fixtures.py" "$WORK/fixtures" >/dev/null

export PYTHONDONTWRITEBYTECODE=1
export DD_HOME="$WORK/home" DD_CHECKS_DIR="$CHECKS_DIR" DD_EXECUTION_MODE="$MODE" DD_EMBEDDED_WORKER=1
export DD_DATA_ROOTS="examples=$EXAMPLES_DIR,qa=$WORK/fixtures,outside=$WORK/outside" DD_BIND_HOST=127.0.0.1
export DD_RUN_TIMEOUT_SECONDS="${DD_RUN_TIMEOUT_SECONDS:-120}" DD_CHECK_TIMEOUT_SECONDS="${DD_CHECK_TIMEOUT_SECONDS:-5}"

# exec: the background PID is the server itself, so cleanup kills exactly this process.
( cd "$WORK" && exec "$BACKEND_PY" -m uvicorn dd_backend.app:create_app --factory --host 127.0.0.1 \
    --port "$PORT" --app-dir "$BACKEND_DIR" >"$WORK/server.log" 2>&1 ) &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; echo "server log: $WORK/server.log"; }
trap cleanup EXIT
# CR3 #6: every request has connect/total deadlines and the whole startup has an overall deadline.
STARTUP_TIMEOUT="${QA_STARTUP_TIMEOUT:-60}"
CURL=(curl -fsS --connect-timeout 2 --max-time 5)
DEADLINE=$((SECONDS + STARTUP_TIMEOUT))
UP=0
while [ "$SECONDS" -lt "$DEADLINE" ]; do
  kill -0 "$PID" 2>/dev/null || { cat "$WORK/server.log" >&2; echo "backend exited during startup" >&2; exit 1; }
  if "${CURL[@]}" "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then UP=1; break; fi
  sleep 0.2
done
[ "$UP" = 1 ] || { echo "backend did not become healthy within ${STARTUP_TIMEOUT}s" >&2; exit 1; }
# Identity: the launched process must still be alive and must own the listening socket on PORT (CR #2).
kill -0 "$PID" 2>/dev/null || { cat "$WORK/server.log" >&2; echo "launched backend died; port $PORT answered by another process" >&2; exit 1; }
if ! ss -ltnpH "sport = :$PORT" 2>/dev/null | grep -q "pid=$PID,"; then
  echo "port $PORT is not owned by launched pid $PID; refusing to test another server" >&2; exit 1
fi
REPORTED="$("${CURL[@]}" "http://127.0.0.1:$PORT/api/session" | "$QA_PY" -c 'import json,sys; print(json.load(sys.stdin)["execution_mode"])')" \
  || { echo "/api/session did not answer within the request deadline" >&2; exit 1; }
[ "$REPORTED" = "$MODE" ] || { echo "server reports execution_mode=$REPORTED, expected $MODE" >&2; exit 1; }
echo "backend pid=$PID mode=$MODE home=$DD_HOME"
# QA_FORCE_EXPECTED_MODE is a self-test hook only (tests/selftest): it must make the suite fail.
QA_BASE_URL="http://127.0.0.1:$PORT" QA_FIXTURE_ROOT=qa QA_FIXTURE_DIR="$WORK/fixtures" QA_OUTSIDE_ROOT=outside \
QA_EXECUTION_MODE="${QA_FORCE_EXPECTED_MODE:-$MODE}" QA_SERVER_HOME="$DD_HOME" \
  "$QA_PY" -m pytest "${@:-$ROOT/tests/http}"
