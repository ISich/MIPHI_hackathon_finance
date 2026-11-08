// Wire DTOs for the D2 backend API.
//
// Source of truth: backend/openapi.json and dd_backend/models.py on main.
// Pivot response fields follow the pinned D4 PivotRollup implementation;
// its response schema is free-form in OpenAPI (see UI_PIVOT_EVIDENCE.md).

export type Iso = string;

export interface DatasetTable { dataset_id: string; side: "before" | "after"; columns: string[]; rows: Array<Array<string | number | boolean | null>> }

export interface AccountUser {
  username: string;
  display_name: string;
}

export interface Session {
  authenticated: boolean;
  kind: "account" | "anonymous-session";
  user: AccountUser | null;
  cookie_secure: boolean;
  execution_mode: string;
}

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
  sources?: string[];
  /** false in the safe builtin-only server mode. */
  custom_execution_enabled?: boolean;
}

/** POST /api/scripts (workspace editor text). */
export interface CreateScriptRequest {
  kind: ScriptKindName;
  name: string;
  code: string;
  params?: Record<string, unknown>;
}

/** POST /api/scripts/upload (multipart, source=file). */
export interface UploadScriptRequest {
  kind: ScriptKindName;
  name: string;
  file: File;
  params?: Record<string, unknown>;
}

export interface ScriptRef {
  /** Omit in a slot to use the built-in procedure. */
  script_id: string;
  params?: Record<string, unknown> | null;
}

export interface Configuration {
  config_id: string;
  name: string;
  dataset_id: string;
  slots: Partial<Record<ProcedureSlot, ScriptRef>>;
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

export interface RunError {
  code: string;
  message: string | null;
}

export interface Run {
  run_id: string;
  status: RunStatus;
  stage: RunStage | null;
  substep?: string | null;
  processed: number | null;
  /** May be null: unknown total ⇒ indeterminate progress, never a made-up percent. */
  total: number | null;
  config_id: string;
  dataset_id: string;
  dataset_revision_id: string;
  initial_check_run_id: string;
  initial_report_id: string;
  report_status: ReportStatus | null;
  checks_completeness: Completeness | null;
  error: RunError | null;
  created_at: Iso;
  started_at: Iso | null;
  finished_at: Iso | null;
  links: Record<string, string>;
}

export interface CreateRunRequest {
  configuration_id: string;
}

export interface RunEvent {
  seq: number;
  ts: Iso;
  check_run_id: string | null;
  stage: string | null;
  substep: string | null;
  level: "INFO" | "WARNING" | "ERROR" | string;
  message: string;
  processed: number | null;
  total: number | null;
  /** "<slot>@<sha12>" — slot for GET /runs/{id}/code/{slot}. */
  code_ref: string | null;
}

export interface EventsPage {
  items: RunEvent[];
  next_after: number;
}

export interface CodeSnapshot {
  run_id: string;
  slot: string;
  script_id: string;
  kind: string;
  source: string;
  name: string;
  script_revision: number;
  code_sha256: string;
  params: Record<string, unknown>;
  code: string;
  check_run_id?: string | null;
}

// ---------------------------------------------------------------- reporting (D4)
export interface Artifact {
  artifact_id: string;
  kind: string;
  rows: number | null;
  bytes: number;
  sha256: string;
  created_at: Iso;
  download: string;
}

/** decision_diff.reporting.summarize() output + run identity + artifacts. */
export interface Summary {
  run_id: string;
  dataset_revision_id?: string;
  total_apps: number;
  changed_apps: number;
  decision_changed_apps: number;
  changed_attributes: number;
  change_types: Record<string, number>;
  approval_rate_before: number;
  approval_rate_after: number;
  /** Up to 20 paths, ranked by distinct changed applications; absent only on older servers. */
  top_paths?: Array<{ path: string; changed_apps: number }>;
  artifacts?: Artifact[];
  [k: string]: unknown;
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
  "CHANGE_TYPE", "DECISION_BEFORE", "DECISION_AFTER", "DECISION_CHANGED", "PRODUCTS",
  "TOP_OFFER_BEFORE", "TOP_OFFER_AFTER", "PARTNER_TYPE", "ROUTING_METHOD",
  "PD_MODEL_BEFORE", "PD_MODEL_AFTER", "CUTOFF_BEFORE", "CUTOFF_AFTER",
  "REJECT_REASON_BEFORE", "REJECT_REASON_AFTER", "SCORE_OKB_BEFORE", "SCORE_OKB_AFTER",
] as const;
export type PivotDimension = (typeof PIVOT_DIMENSIONS)[number] | string;

export interface PivotFilter {
  dim: PivotDimension;
  op: "eq" | "in";
  values: Array<string | number>;
}

/** Wire contract from backend PivotQuery / pinned PivotRollup.cells. */
export interface PivotRequest {
  dimensions: PivotDimension[];
  filters: Record<string, string | number | boolean | null | Array<string | number | boolean | null>>;
  limit?: number;
  offset?: number;
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
  data_revision: string;
  items: Array<{ dimensions: Record<string, string | number | null>; cnt: number; group_locator: string }>;
  total: number;
  limit: number;
  offset: number;
}

export interface ApplicationsPage {
  run_id: string;
  group?: string;
  items: string[];
  /** Full distinct total after filters — or null when the backend cannot provide it. */
  total: number | null;
  total_note?: string;
  offset?: number;
  limit: number;
}

/** One D4 base pivot fact (DuckDBMart.pivot). CNT must not be summed across groups. */
export type PivotFact = Record<string, string | number | null> & { CNT: number; SOURCE: "BEFORE" | "AFTER" };

export interface PivotFactsPage {
  run_id: string;
  items: PivotFact[];
  limit: number;
  offset: number;
  next_offset: number | null;
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

/** SUCCEEDED = check ran (verdict in rows). Everything else = execution error, never a FAIL. */
export type ExecutionStatus =
  | "SUCCEEDED"
  | "ERROR"
  | "TIMEOUT"
  | "INVALID_OUTPUT"
  | "IMPORT_ERROR"
  | "CONTRACT_ERROR"
  | "DUPLICATE_ID";

export interface CheckExecution {
  execution_id: string;
  slot: string;
  script_id: string;
  check_id: string | null;
  label: string | null;
  params: Record<string, unknown>;
  execution_status: ExecutionStatus;
  rows_count: number;
  diagnostics?: Array<Record<string, unknown>>;
  duration_seconds: number | null;
}

export type ReportStatus = "PENDING" | "PUBLISHED" | "FAILED";
export type Completeness = "COMPLETE" | "INCOMPLETE" | "NO_CHECKS_SELECTED";

export interface Report {
  report_id: string;
  run_id: string;
  dataset_revision_id: string;
  check_run_id: string;
  status: ReportStatus;
  completeness: Completeness | null;
  sha256: string | null;
  created_at: Iso;
  published_at: Iso | null;
  links: Record<string, string>;
}

export interface ReportList {
  run_id: string;
  initial_report_id: string;
  items: Report[];
}

/** Published report document (D4 format). Rows of all executions are flat in `checks`, in execution order. */
export interface ReportChecks {
  report_id: string;
  run_id: string;
  check_run_id: string;
  dataset_revision_id: string;
  completeness: Completeness | string;
  summary: Record<string, unknown>;
  checks: CheckRow[];
  diagnostics: Array<{ check?: string; error_type?: string; message?: string; [k: string]: unknown }>;
  timings_seconds: Record<string, number | null>;
  executions: CheckExecution[];
}

export type AiOpinionStatus = "DISABLED" | "NOT_REQUESTED" | "PENDING" | "READY" | "FAILED";

export interface AiFinding {
  title: string;
  text: string;
  severity: "info" | "attention" | "concern";
  refs: string[];
  unverified_numbers: number[];
}

/** Separate AI block of a check report (FR-024): never changes counts / RESULT / CONFIDENCE. */
export interface AiOpinion {
  report_id: string;
  status: AiOpinionStatus;
  opinion_id: string | null;
  model: string | null;
  prompt_revision: string;
  disclaimer: string;
  disabled_reason: string | null;
  opinion: { summary: string; findings: AiFinding[]; limitations: string[] } | null;
  validation: { findings_received?: number; findings_kept?: number; dropped?: Array<Record<string, unknown>> } | null;
  usage: Record<string, number | null> | null;
  error: { code: string; message: string | null } | null;
  facts: Record<string, Record<string, unknown>> | null;
  created_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
}

export interface CheckRun {
  check_run_id: string;
  run_id: string;
  dataset_revision_id: string;
  report_id: string;
  initial: boolean;
  status: RunStatus;
  selected: Array<Record<string, unknown>>;
  executions: CheckExecution[];
  error: RunError | null;
  created_at: Iso;
  started_at: Iso | null;
  finished_at: Iso | null;
  links: Record<string, string>;
}

export interface CreateCheckRunRequest {
  checks: ScriptRef[];
}

export interface Readiness {
  ready: boolean;
  execution_mode?: string;
  warnings?: string[];
  checks?: Array<Record<string, unknown>>;
  [k: string]: unknown;
}
