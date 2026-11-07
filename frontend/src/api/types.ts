// Wire DTOs for the D2 backend API.
//
// Sources (in priority order):
//  1. backend-night FastAPI code (feat/backend-night) — registry views for
//     datasets / scripts / script-kinds / configurations, error envelope.
//  2. docs/contracts/api.md + execution.md (docs SHA 3731ae3) — runs, events,
//     reports, check runs, pivot, drill-down. These are the agreed semantics,
//     wire names must be re-checked against the exported OpenAPI.
// Divergences are logged in night-ui.log.md / UI_RESULT.md.

export type Iso = string;

/** Error envelope: {code, message, details, request_id}. */
export interface ErrorEnvelope {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset?: number;
  limit?: number;
  next_offset?: number | null;
}

// ---------------------------------------------------------------- registry
export interface DatasetRevision {
  revision_id: string;
  fingerprint: string;
  pairs: number;
  missing_before: string[];
  missing_after: string[];
  created_at: Iso;
}

export interface Dataset {
  dataset_id: string;
  name: string;
  shared: boolean;
  root: string;
  mode: "files" | "dirs";
  before: string;
  after: string;
  created_at: Iso;
  revisions: DatasetRevision[];
}

export const PROCEDURE_SLOTS = ["normalize", "compare", "segments", "aggregate"] as const;
export type ProcedureSlot = (typeof PROCEDURE_SLOTS)[number];
export type ScriptKindName = ProcedureSlot | "check";
export type ScriptSource = "builtin" | "workspace" | "file";

export interface Script {
  script_id: string;
  kind: ScriptKindName;
  source: ScriptSource;
  name: string;
  filename: string | null;
  builtin_ref: string | null;
  shared: boolean;
  params: Record<string, unknown>;
  revision: number;
  code_sha256: string;
  created_at: Iso;
  updated_at: Iso;
  code?: string;
}

export interface ScriptKind {
  kind: ScriptKindName;
  entrypoint: string;
  output_columns: string[];
  template: string;
  example: string;
}

export interface CreateScriptRequest {
  kind: ScriptKindName;
  source: "workspace" | "file";
  name: string;
  code: string;
  filename?: string;
  params?: Record<string, unknown>;
}

export interface ScriptRef {
  script_id: string;
  params?: Record<string, unknown> | null;
}

export interface Configuration {
  config_id: string;
  name: string;
  dataset_id: string;
  slots: Record<ProcedureSlot, ScriptRef>;
  checks: ScriptRef[];
  created_at: Iso;
}

export interface CreateConfigurationRequest {
  name: string;
  dataset_id: string;
  slots: Partial<Record<ProcedureSlot, ScriptRef>>;
  /** null/undefined = server default (all shared built-in checks). */
  checks?: ScriptRef[] | null;
}

// ---------------------------------------------------------------- runs
export type RunStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
export const RUN_STAGES = [
  "VALIDATING",
  "NORMALIZING",
  "COMPARING",
  "AGGREGATING",
  "CHECKING",
  "FINALIZING",
] as const;
export type RunStage = (typeof RUN_STAGES)[number];

export interface Run {
  run_id: string;
  config_id: string;
  dataset_id?: string;
  data_revision?: string | null;
  status: RunStatus;
  stage: RunStage | string | null;
  processed?: number | null;
  /** May be absent: unknown total ⇒ indeterminate progress, never a made-up percent. */
  total?: number | null;
  created_at: Iso;
  started_at?: Iso | null;
  finished_at?: Iso | null;
  initial_report_id?: string | null;
  completeness?: Record<string, unknown> | null;
  diagnostics?: Array<Record<string, unknown>> | null;
  error?: ErrorEnvelope | null;
}

export interface CreateRunRequest {
  config_id: string;
  idempotency_key?: string;
}

export interface Accepted {
  run_id?: string;
  check_run_id?: string;
  report_id?: string;
  status: string;
  status_url?: string;
}

export interface RunEvent {
  seq: number;
  run_id: string;
  stage: string | null;
  level: "INFO" | "WARNING" | "ERROR" | string;
  message: string;
  processed?: number | null;
  total?: number | null;
  ts: Iso;
  code_ref?: string | null;
}

export interface EventsPage {
  items: RunEvent[];
  /** Highest seq returned; pass back as ?after=. */
  last_seq?: number;
}

export interface CodeSnapshot {
  run_id: string;
  stage: string;
  script_id?: string;
  code_sha256?: string;
  code: string;
}

// ---------------------------------------------------------------- reporting (D4)
export interface Summary {
  run_id: string;
  data_revision?: string | null;
  total_apps: number;
  changed_apps: number;
  decision_changed_apps: number;
  changed_attributes: number;
  change_types: Record<string, number>;
  approval_rate_before: number;
  approval_rate_after: number;
  top_paths?: Array<{ path: string; changed_apps: number }>;
  completeness?: Record<string, unknown> | null;
  diagnostics?: Array<Record<string, unknown>> | null;
}

export const PIVOT_DIMENSIONS = [
  "PREFIX",
  "CLASS",
  "SUFFIX",
  "PATH",
  "ARRAY_KEY",
  "KEY",
  "VALUE_ADJUSTED",
  "SOURCE",
  "DIFF_FLAG",
  "CHANGE_TYPE",
  "DECISION_CHANGED",
] as const;
export type PivotDimension = (typeof PIVOT_DIMENSIONS)[number] | string;

export interface PivotFilter {
  dim: PivotDimension;
  op: "eq" | "in";
  values: Array<string | number>;
}

export interface PivotRequest {
  rows: PivotDimension[];
  cols: PivotDimension[];
  filters: PivotFilter[];
  report_id?: string | null;
  limit?: number;
}

export interface PivotCell {
  row: Array<string | number | null>;
  col: Array<string | number | null>;
  /** COUNT(DISTINCT APP_ID) for the cell, computed server-side. */
  count: number;
  /** Opaque locator; passed back unchanged for drill-down. */
  group: string;
}

export interface PivotTotal {
  key: Array<string | number | null>;
  count: number;
  group: string;
}

export interface PivotResponse {
  run_id: string;
  data_revision?: string | null;
  rows: PivotDimension[];
  cols: PivotDimension[];
  cells: PivotCell[];
  row_totals: PivotTotal[];
  col_totals: PivotTotal[];
  grand_total: { count: number; group: string };
  truncated?: boolean;
}

export interface ApplicationsPage extends Page<string> {
  run_id: string;
  group: string;
}

export interface ComparisonRow {
  APP_ID: string;
  PREFIX: string;
  CLASS: string;
  SUFFIX: string;
  ARRAY_KEY: string;
  KEY: string;
  PATH: string;
  VALUE_BEFORE: string;
  VALUE_AFTER: string;
  ADJUSTED_BEFORE: string;
  ADJUSTED_AFTER: string;
  DIFF_FLAG: number;
  CHANGE_TYPE: "SAME" | "VALUE_CHANGED" | "ATTRIBUTE_NEW" | "ATTRIBUTE_LOST";
}

export interface ApplicationDetail {
  run_id: string;
  app_id: string;
  segment: Record<string, unknown>;
  comparison: ComparisonRow[];
}

// ---------------------------------------------------------------- checks / reports
export interface CheckRow {
  LABEL: string;
  SOURCE: "BEFORE" | "AFTER";
  ARGUMENT: string;
  CNT: number;
  TOTAL: number;
  METRIC: number;
  /** K examples only — never the CNT population. */
  APP_IDS: string[];
  RESULT: "PASS" | "FAIL";
  CONFIDENCE: "HIGH" | "LOW";
}

/** SUCCESS = check ran; business verdict is in rows. Others = execution error, not FAIL. */
export type ExecutionStatus =
  | "SUCCESS"
  | "ERROR"
  | "TIMEOUT"
  | "INVALID_OUTPUT"
  | "IMPORT_ERROR"
  | "DUPLICATE_ID"
  | "SKIPPED"
  | string;

export interface CheckExecution {
  execution_id: string;
  check_id: string | null;
  script_id?: string | null;
  label?: string | null;
  execution_status: ExecutionStatus;
  params: Record<string, unknown>;
  diagnostics?: { error_type?: string; message?: string; [k: string]: unknown } | null;
  duration_s?: number | null;
  rows: CheckRow[];
}

export type ReportStatus = "PENDING" | "RUNNING" | "READY" | "FAILED" | string;

export interface Report {
  report_id: string;
  run_id: string;
  data_revision?: string | null;
  check_run_id: string;
  status: ReportStatus;
  created_at: Iso;
  is_initial?: boolean;
  completeness?: Record<string, unknown> | null;
}

export interface ReportChecks {
  report_id: string;
  run_id: string;
  check_run_id: string;
  status: ReportStatus;
  executions: CheckExecution[];
}

export type CheckRunStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | string;

export interface CheckRun {
  check_run_id: string;
  run_id: string;
  data_revision?: string | null;
  report_id: string;
  status: CheckRunStatus;
  checks: ScriptRef[];
  created_at: Iso;
  error?: ErrorEnvelope | null;
}

export interface CreateCheckRunRequest {
  checks: ScriptRef[];
}

export interface Readiness {
  ready: boolean;
  execution_mode?: string;
  [k: string]: unknown;
}
