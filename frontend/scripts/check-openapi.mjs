// Contract check: every route the UI client calls must exist in the backend's
// OpenAPI, and the response fields the UI reads must be declared there.
// Usage: node scripts/check-openapi.mjs <path-to-openapi.json | http://127.0.0.1:8765/openapi.json>
import { readFileSync } from "node:fs";

const src = process.argv[2];
if (!src) {
  console.error("usage: node scripts/check-openapi.mjs <openapi.json|url>");
  process.exit(2);
}
const spec = src.startsWith("http") ? await (await fetch(src)).json() : JSON.parse(readFileSync(src, "utf8"));

// [method, path, schema name whose properties the UI reads (or null)]
const USED = [
  ["get", "/ready", null],
  ["get", "/api/session", null],
  ["get", "/api/datasets", "Dataset"],
  ["get", "/api/scripts", "Script"],
  ["post", "/api/scripts", "Script"],
  ["post", "/api/scripts/upload", "Script"],
  ["get", "/api/scripts/{script_id}", "Script"],
  ["get", "/api/script-kinds", "ScriptKind"],
  ["get", "/api/configurations", "Configuration"],
  ["post", "/api/configurations", "Configuration"],
  ["get", "/api/configurations/{config_id}", "Configuration"],
  ["post", "/api/runs", "Run"],
  ["get", "/api/runs", "RunPage"],
  ["get", "/api/runs/{run_id}", "Run"],
  ["get", "/api/runs/{run_id}/events", "EventPage"],
  ["get", "/api/runs/{run_id}/code/{slot}", "CodeSnapshot"],
  ["get", "/api/check-runs/{check_run_id}/code/{slot}", "CodeSnapshot"],
  ["get", "/api/runs/{run_id}/summary", null],
  ["post", "/api/runs/{run_id}/pivot", null],
  ["get", "/api/runs/{run_id}/groups/{group}/applications", null],
  ["get", "/api/runs/{run_id}/pivot-facts", null],
  ["post", "/api/runs/{run_id}/pivot-facts/applications", null],
  ["get", "/api/runs/{run_id}/applications/{app_id}", null],
  ["get", "/api/runs/{run_id}/reports", "ReportList"],
  ["post", "/api/runs/{run_id}/check-runs", "CheckRun"],
  ["get", "/api/check-runs/{check_run_id}", "CheckRun"],
  ["get", "/api/reports/{report_id}/checks", "ReportChecks"],
  ["get", "/api/reports/{report_id}/checks.html", null],
];
const READS = {
  Dataset: ["dataset_id", "name", "revisions"],
  Script: ["script_id", "kind", "source", "name", "revision", "code_sha256", "shared"],
  ScriptKind: ["kind", "entrypoint", "output_columns", "template", "example", "custom_execution_enabled"],
  Configuration: ["config_id", "name", "dataset_id", "checks"],
  Run: ["run_id", "status", "stage", "substep", "processed", "total", "config_id", "dataset_revision_id", "initial_report_id", "report_status", "checks_completeness", "error", "created_at"],
  RunPage: ["items", "total"],
  EventPage: ["items", "next_after"],
  Event: ["seq", "ts", "stage", "substep", "level", "message", "code_ref"],
  CodeSnapshot: ["slot", "name", "source", "script_revision", "code_sha256", "params", "code"],
  ReportList: ["initial_report_id", "items"],
  Report: ["report_id", "status", "completeness"],
  CheckRun: ["check_run_id", "report_id", "status", "error"],
  ReportChecks: ["report_id", "completeness", "checks", "diagnostics", "executions"],
  Execution: ["execution_id", "slot", "check_id", "label", "params", "execution_status", "rows_count", "duration_seconds"],
  ErrorBody: ["code", "message", "details", "request_id"],
};
const EXEC_STATUSES = ["SUCCEEDED", "ERROR", "TIMEOUT", "INVALID_OUTPUT", "IMPORT_ERROR", "CONTRACT_ERROR", "DUPLICATE_ID"];

let problems = 0;
const fail = (m) => (problems++, console.log("FAIL " + m));
for (const [method, path] of USED) {
  if (!spec.paths?.[path]?.[method]) fail(`route missing: ${method.toUpperCase()} ${path}`);
  else console.log(`ok   ${method.toUpperCase()} ${path}`);
}
const schemas = spec.components?.schemas ?? {};
for (const [name, fields] of Object.entries(READS)) {
  const sch = schemas[name];
  if (!sch) {
    fail(`schema missing: ${name}`);
    continue;
  }
  for (const f of fields) if (!sch.properties?.[f]) fail(`${name}.${f} not in schema`);
}
const es = schemas.Execution?.properties?.execution_status?.enum;
if (es) for (const s of es) if (!EXEC_STATUSES.includes(s)) fail(`execution_status ${s} unknown to UI`);
const runReq = schemas.RunCreate?.properties;
if (runReq && !runReq.configuration_id) fail("RunCreate.configuration_id missing");
console.log(problems ? `\n${problems} problem(s)` : "\nOpenAPI contract check: OK");
process.exit(problems ? 1 : 0);
