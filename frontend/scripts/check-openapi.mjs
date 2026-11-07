// Contract check of the UI client against the backend OpenAPI.
//  - every route the client calls exists;
//  - each route's 2xx JSON response is bound to the schema the UI parses
//    (object $ref, or array of $ref for list endpoints);
//  - each request body is bound to the expected schema, the fields the UI sends
//    exist, and every field the backend requires is sent by the UI;
//  - fields the UI reads have the expected type; fields the UI treats as
//    non-null are required and not nullable.
// Usage: node scripts/check-openapi.mjs <path-to-openapi.json | http://127.0.0.1:8765/openapi.json>
import { readFileSync } from "node:fs";

const src = process.argv[2];
if (!src) {
  console.error("usage: node scripts/check-openapi.mjs <openapi.json|url>");
  process.exit(2);
}
const spec = src.startsWith("http") ? await (await fetch(src)).json() : JSON.parse(readFileSync(src, "utf8"));
const schemas = spec.components?.schemas ?? {};

// [method, path, response binding]: "Name" = object $ref, "Name[]" = array of $ref, null = free-form/not parsed by schema
const ROUTES = [
  ["get", "/ready", null],
  ["get", "/api/session", "Session"],
  ["post", "/api/auth/login", "Session"],
  ["post", "/api/auth/logout", "Session"],
  ["get", "/api/datasets", "Dataset[]"],
  ["get", "/api/scripts", "Script[]"],
  ["post", "/api/scripts", "Script"],
  ["post", "/api/scripts/upload", "Script"],
  ["get", "/api/scripts/{script_id}", "Script"],
  ["get", "/api/script-kinds", "ScriptKind[]"],
  ["get", "/api/configurations", "Configuration[]"],
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

// Request bodies the UI sends: schema binding + the fields the client puts in the body.
const REQUESTS = {
  "post /api/auth/login": { schema: "LoginRequest", sends: ["username", "password"] },
  "post /api/runs/{run_id}/pivot": { schema: "PivotQuery", sends: ["dimensions", "filters", "limit", "offset"] },
  "post /api/runs": { schema: "RunCreate", sends: ["configuration_id"] },
  "post /api/configurations": { schema: "ConfigurationCreate", sends: ["name", "dataset_id", "slots", "checks"] },
  "post /api/scripts": { schema: "ScriptCreate", sends: ["kind", "name", "code", "params"] },
  "post /api/runs/{run_id}/check-runs": { schema: "CheckRunCreate", sends: ["checks"] },
  "post /api/runs/{run_id}/pivot-facts/applications": { schema: "PivotDrillDown", sends: ["group", "limit"] },
  "post /api/scripts/upload": { multipart: true, sends: ["kind", "name", "params", "file"] },
};

// Fields the UI reads: type letter + "?" when the UI handles null/absence.
// s=string i=integer n=number b=boolean a=array o=object
const FIELDS = {
  Session: "authenticated:b kind:s user:o? cookie_secure:b execution_mode:s",
  AccountUser: "username:s display_name:s",
  PivotQuery: "dimensions:a filters:o? limit:i? offset:i?",
  Run: "run_id:s status:s stage:s? substep:s? processed:i? total:i? config_id:s dataset_revision_id:s initial_report_id:s report_status:s? checks_completeness:s? error:o? created_at:s",
  RunPage: "items:a total:i",
  EventPage: "items:a next_after:i",
  Event: "seq:i ts:s check_run_id:s? stage:s? substep:s? level:s message:s processed:i? total:i? code_ref:s?",
  CodeSnapshot: "slot:s name:s source:s script_revision:i code_sha256:s params:o code:s",
  Dataset: "dataset_id:s name:s revisions:a",
  DatasetRevision: "revision_id:s pairs:i",
  Script: "script_id:s kind:s source:s name:s revision:i code_sha256:s shared:b",
  ScriptKind: "kind:s entrypoint:s output_columns:a template:s example:s custom_execution_enabled:b",
  Configuration: "config_id:s name:s dataset_id:s checks:a",
  ReportList: "initial_report_id:s items:a",
  Report: "report_id:s run_id:s status:s completeness:s?",
  CheckRun: "check_run_id:s run_id:s report_id:s status:s error:o?",
  ReportChecks: "report_id:s run_id:s check_run_id:s dataset_revision_id:s completeness:s checks:a diagnostics:a executions:a",
  ErrorBody: "code:s message:s details:o request_id:s",
};
const TYPE = { s: "string", i: "integer", n: "number", b: "boolean", a: "array", o: "object" };
const EXEC_STATUSES = ["SUCCEEDED", "ERROR", "TIMEOUT", "INVALID_OUTPUT", "IMPORT_ERROR", "CONTRACT_ERROR", "DUPLICATE_ID"];

let problems = 0;
const fail = (m) => (problems++, console.log("FAIL " + m));
const refName = (s) => (s && typeof s.$ref === "string" ? s.$ref.split("/").pop() : null);

/** {types:Set<string>, nullable:boolean} of a property schema. */
function typeOf(s) {
  if (!s) return { types: new Set(), nullable: false };
  if (s.$ref) return { types: new Set(["object"]), nullable: false };
  const alts = s.anyOf ?? s.oneOf;
  if (alts) {
    const parts = alts.map(typeOf);
    return { types: new Set(parts.flatMap((p) => [...p.types])), nullable: parts.some((p) => p.nullable) };
  }
  if (s.allOf) return typeOf(s.allOf[0]);
  if (s.type === "null") return { types: new Set(), nullable: true };
  if (Array.isArray(s.type)) return { types: new Set(s.type.filter((t) => t !== "null")), nullable: s.type.includes("null") };
  if (s.type) return { types: new Set([s.type]), nullable: !!s.nullable };
  return { types: new Set(["any"]), nullable: true };
}

function jsonSchemaOf(op, kind) {
  if (kind === "response") {
    const code = Object.keys(op.responses ?? {}).find((c) => c.startsWith("2"));
    return code ? op.responses[code].content?.["application/json"]?.schema : undefined;
  }
  return op.requestBody?.content;
}

// routes + response bindings
for (const [method, path, binding] of ROUTES) {
  const op = spec.paths?.[path]?.[method];
  const label = `${method.toUpperCase()} ${path}`;
  if (!op) {
    fail(`route missing: ${label}`);
    continue;
  }
  if (!binding) continue;
  const schema = jsonSchemaOf(op, "response");
  const list = binding.endsWith("[]");
  const want = list ? binding.slice(0, -2) : binding;
  const got = list ? (schema?.type === "array" ? refName(schema.items) : null) : refName(schema);
  if (got !== want) fail(`${label}: response bound to ${got ?? JSON.stringify(schema)?.slice(0, 80)}, expected ${binding}`);
}

// request bodies
for (const [key, req] of Object.entries(REQUESTS)) {
  const [method, path] = key.split(" ");
  const op = spec.paths?.[path]?.[method];
  if (!op) continue; // already reported as missing route
  const content = jsonSchemaOf(op, "request") ?? {};
  let schema;
  if (req.multipart) {
    const s = content["multipart/form-data"]?.schema;
    schema = refName(s) ? schemas[refName(s)] : s;
    if (!schema) {
      fail(`${key}: no multipart/form-data body`);
      continue;
    }
  } else {
    const name = refName(content["application/json"]?.schema);
    if (name !== req.schema) {
      fail(`${key}: request body bound to ${name}, expected ${req.schema}`);
      continue;
    }
    schema = schemas[name];
  }
  const props = schema?.properties ?? {};
  for (const f of req.sends) if (!props[f]) fail(`${req.schema ?? key}.${f}: UI sends it but the schema has no such field`);
  for (const f of schema?.required ?? []) if (!req.sends.includes(f)) fail(`${req.schema ?? key}.${f}: required by backend but not sent by the UI`);
}

// fields the UI reads
for (const [name, spec_] of Object.entries(FIELDS)) {
  const sch = schemas[name];
  if (!sch) {
    fail(`schema missing: ${name}`);
    continue;
  }
  const required = new Set(sch.required ?? []);
  for (const item of spec_.split(" ")) {
    const [field, t] = item.split(":");
    const optional = t.endsWith("?");
    const want = TYPE[t[0]];
    const prop = sch.properties?.[field];
    if (!prop) {
      fail(`${name}.${field}: not in schema`);
      continue;
    }
    const got = typeOf(prop);
    if (!got.types.has(want) && !got.types.has("any") && !(want === "number" && got.types.has("integer")))
      fail(`${name}.${field}: type ${[...got.types].join("|") || "null"}, UI expects ${want}`);
    if (!optional && (got.nullable || !required.has(field)))
      fail(`${name}.${field}: UI treats it as always present and non-null, schema has ${got.nullable ? "nullable" : ""}${!required.has(field) ? " optional" : ""}`);
  }
}

const es = schemas.Execution?.properties?.execution_status?.enum;
if (es) for (const s of es) if (!EXEC_STATUSES.includes(s)) fail(`execution_status ${s} unknown to UI`);

console.log(problems ? `\n${problems} problem(s)` : "OpenAPI contract check: OK");
process.exit(problems ? 1 : 0);
