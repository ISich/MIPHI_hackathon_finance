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
BACKEND_PY="${BACKEND_PY:-$BACKEND_DIR/.venv/bin/python}"
PORT="${QA_PORT:-18765}"
QA_PY="${QA_PY:-$ROOT/.venv/bin/python}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/qa-http-XXXXXX")"
CHECKS_DIR="$("$ROOT/scripts/fetch_core_checks.sh")"
EXAMPLES_DIR="$(dirname "$CHECKS_DIR")/examples"
"$QA_PY" "$ROOT/scripts/make_http_fixtures.py" "$WORK/fixtures" >/dev/null

export PYTHONDONTWRITEBYTECODE=1
export DD_HOME="$WORK/home" DD_CHECKS_DIR="$CHECKS_DIR" DD_EXECUTION_MODE="$MODE" DD_EMBEDDED_WORKER=1
export DD_DATA_ROOTS="examples=$EXAMPLES_DIR,qa=$WORK/fixtures" DD_BIND_HOST=127.0.0.1
export DD_RUN_TIMEOUT_SECONDS="${DD_RUN_TIMEOUT_SECONDS:-120}" DD_CHECK_TIMEOUT_SECONDS="${DD_CHECK_TIMEOUT_SECONDS:-5}"

# exec: the background PID is the server itself, so cleanup kills exactly this process.
( cd "$WORK" && exec "$BACKEND_PY" -m uvicorn dd_backend.app:create_app --factory --host 127.0.0.1 \
    --port "$PORT" --app-dir "$BACKEND_DIR" >"$WORK/server.log" 2>&1 ) &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; echo "server log: $WORK/server.log"; }
trap cleanup EXIT
for _ in $(seq 1 100); do
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  kill -0 "$PID" 2>/dev/null || { cat "$WORK/server.log"; exit 1; }
  sleep 0.2
done
echo "backend pid=$PID mode=$MODE home=$DD_HOME"
QA_BASE_URL="http://127.0.0.1:$PORT" QA_FIXTURE_ROOT=qa QA_FIXTURE_DIR="$WORK/fixtures" QA_EXECUTION_MODE="$MODE" \
  "$QA_PY" -m pytest "${@:-$ROOT/tests/http}"
