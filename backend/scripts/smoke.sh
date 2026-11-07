#!/usr/bin/env bash
# Real HTTP smoke test on loopback: start server (+embedded worker), register the core
# fixture as a shared dataset, run the full pipeline with the 5 organizer checks, poll,
# fetch summary/checks/HTML, start a check-only run. Saves real responses to $OUT.
#
# Usage: backend/scripts/smoke.sh [OUT_DIR]      (requires backend/.venv and fetch_core.sh)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-$here/.venv/bin/python}"
OUT="${1:-$here/var/smoke}"
PORT="${PORT:-$("$PY" -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')}"
BASE="http://127.0.0.1:$PORT"
core="$("$here/scripts/fetch_core.sh")"
export DD_HOME="${DD_HOME:-$(mktemp -d)}"
export DD_DATA_ROOTS="examples=$core/examples"
export DD_CHECKS_DIR="$core/checks"
mkdir -p "$OUT"
jar="$OUT/cookies.txt"; rm -f "$jar"

cd "$here"
"$PY" -m dd_backend register-dataset --name "core fixture I32554354" --root examples --mode files \
  --before I32554354_other.json --after I32554354.json > "$OUT/00_register_dataset_cli.json"

"$PY" -m dd_backend serve --host 127.0.0.1 --port "$PORT" > "$OUT/server.log" 2>&1 &
server=$!
trap 'kill $server 2>/dev/null || true; wait $server 2>/dev/null || true' EXIT

for _ in $(seq 1 100); do curl -fsS "$BASE/health" >/dev/null 2>&1 && break; sleep 0.1; done

save() { # name method path [json-body] [extra curl args...]
  local name=$1 method=$2 path=$3 body=${4:-}; shift 4 || shift $#
  local args=(-sS -b "$jar" -c "$jar" -X "$method" -o "$OUT/$name.json" -w '%{http_code}' "$@")
  [ -n "$body" ] && args+=(-H 'content-type: application/json' --data "$body") && printf '%s\n' "$body" > "$OUT/$name.request.json"
  local code; code=$(curl "${args[@]}" "$BASE$path")
  echo "$method $path -> $code" | tee -a "$OUT/requests.log"
}
j() { "$PY" -c "import json,sys;d=json.load(open('$OUT/$1.json'));print(eval('d'+sys.argv[1]))" "$2"; }

save 01_health GET /health
save 02_ready GET /ready
curl -sS "$BASE/openapi.json" -o "$OUT/openapi.json"
save 03_datasets GET /api/datasets
ds=$(j 03_datasets '[0]["dataset_id"]')
save 04_scripts GET /api/scripts
save 05_script_kinds GET /api/script-kinds
save 06_configuration POST /api/configurations "{\"name\":\"smoke\",\"dataset_id\":\"$ds\"}"
cfg=$(j 06_configuration '["config_id"]')
save 07_run_accepted POST /api/runs "{\"configuration_id\":\"$cfg\"}" -H "Idempotency-Key: smoke-$PORT"
run=$(j 07_run_accepted '["run_id"]')
save 07b_run_replay POST /api/runs "{\"configuration_id\":\"$cfg\"}" -H "Idempotency-Key: smoke-$PORT"
for _ in $(seq 1 600); do
  save 08_run_status GET "/api/runs/$run" >/dev/null
  st=$(j 08_run_status '["status"]'); [ "$st" = COMPLETED ] || [ "$st" = FAILED ] && break; sleep 0.2
done
echo "run $run status=$st" | tee -a "$OUT/requests.log"
save 09_events GET "/api/runs/$run/events?after=0"
save 10_summary GET "/api/runs/$run/summary"
save 11_artifacts GET "/api/runs/$run/artifacts"
save 12_code_normalize GET "/api/runs/$run/code/normalize"
save 13_checks_initial GET "/api/runs/$run/checks"
rep=$(j 08_run_status '["initial_report_id"]')
curl -sS -b "$jar" "$BASE/api/reports/$rep/checks.html" -o "$OUT/14_report.html"
save 15_pivot_facts GET "/api/runs/$run/pivot-facts?limit=3"
save 16_application GET "/api/runs/$run/applications/I32554354"
save 17_drilldown POST "/api/runs/$run/pivot-facts/applications" '{"group":{"SOURCE":"AFTER","PATH":"decisionResult.decision"}}'
save 18_pivot_rollup_501 POST "/api/runs/$run/pivot" '{}'
check=$("$PY" -c "import json;print([s['script_id'] for s in json.load(open('$OUT/04_scripts.json')) if s['kind']=='check'][0])")
save 19_check_run_accepted POST "/api/runs/$run/check-runs" "{\"checks\":[{\"script_id\":\"$check\",\"params\":{\"max_drop_rel\":0.0}}]}" -H "Idempotency-Key: smoke-cr-$PORT"
cr=$(j 19_check_run_accepted '["check_run_id"]')
for _ in $(seq 1 300); do
  save 20_check_run_status GET "/api/check-runs/$cr" >/dev/null
  cst=$(j 20_check_run_status '["status"]'); [ "$cst" = COMPLETED ] || [ "$cst" = FAILED ] && break; sleep 0.2
done
save 21_reports GET "/api/runs/$run/reports"
save 22_error_not_found GET "/api/runs/run_doesnotexist"
save 23_error_idempotency_required POST /api/runs "{\"configuration_id\":\"$cfg\"}"
rm -f "$jar"
echo "SMOKE run=$run status=$st check_run=$cr status=$cst out=$OUT"
[ "$st" = COMPLETED ] && [ "$cst" = COMPLETED ]
