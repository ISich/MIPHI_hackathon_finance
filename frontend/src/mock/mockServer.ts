// =============================================================================
// DEVELOPMENT-ONLY MOCK BACKEND. NOT A REAL CALCULATION.
//
// A `fetch` replacement that mirrors the wire format of backend-night
// (dd_backend/models.py, read 2026-11-07), so the real ApiClient code path is
// exercised. All data is synthetic (APP_ID "MOCK-…"); numbers are NOT
// produced by decision_diff. Enabled only with `vite --mode mock`; the UI then
// shows a permanent MOCK banner. Never use it as evidence of E2E.
// =============================================================================
import type {
  CheckExecution,
  CheckRow,
  CheckRun,
  ComparisonRow,
  Configuration,
  Dataset,
  Report,
  ReportChecks,
  Run,
  RunEvent,
  Script,
  ScriptKind,
  ScriptRef,
} from "../api/types";
import { PROCEDURE_SLOTS, RUN_STAGES, PIVOT_DIMENSIONS } from "../api/types";

export interface MockOptions {
  /** Mirrors backend DD_EXECUTION_MODE: false = builtin-only (backend default). */
  customExecution: boolean;
  /**
   * Current PivotQuery/items wire contract. Explicit false tests old 501 servers.
   */
  serverPivot?: boolean;
  /** How many GET polls a run needs per stage. */
  ticksPerStage?: number;
  /** Page size of GET /runs/{id}/events (backend default limit: 500). */
  eventsPageLimit?: number;
  /** Extra progress events per stage (to produce long journals). */
  extraEventsPerStage?: number;
}

type Json = Record<string, unknown>;
const NOW = "2026-11-07T00:00:00Z";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "x-request-id": "mock" },
  });
}
function err(status: number, code: string, message: string, details: Json = {}): Response {
  return json(status, { code, message, details, request_id: "mock" });
}

// ------------------------------------------------------------- fixture data
const APPS = ["MOCK-0001", "MOCK-0002", "MOCK-0003", "MOCK-0004", "MOCK-0005", "MOCK-0006"];

function cmp(app: string, path: string, before: string, after: string, type: ComparisonRow["CHANGE_TYPE"], arrayKey = ""): ComparisonRow {
  const parts = path.split(".");
  return {
    APP_ID: app,
    PREFIX: parts[0] ?? "",
    CLASS: parts[1] ?? "",
    SUFFIX: parts.slice(2).join("."),
    ARRAY_KEY: arrayKey,
    KEY: parts[parts.length - 1] ?? "",
    PATH: path,
    VALUE_BEFORE: before,
    VALUE_AFTER: after,
    ADJUSTED_BEFORE: before,
    ADJUSTED_AFTER: after,
    DIFF_FLAG: type === "SAME" ? 0 : 1,
    CHANGE_TYPE: type,
  };
}

const COMPARISON: ComparisonRow[] = [
  cmp("MOCK-0001", "decision.result.decision", "REJECT", "APPROVE", "VALUE_CHANGED"),
  cmp("MOCK-0001", "score.okb.value", "610", "640", "VALUE_CHANGED"),
  cmp("MOCK-0002", "decision.result.decision", "APPROVE", "APPROVE", "SAME"),
  cmp("MOCK-0002", "score.okb.value", "700", "700", "SAME"),
  cmp("MOCK-0002", "rules.stop.factor", "SF_12", "", "ATTRIBUTE_LOST", "P1|SF_12"),
  cmp("MOCK-0003", "decision.result.decision", "APPROVE", "REJECT", "VALUE_CHANGED"),
  cmp("MOCK-0003", "model.pd.name", "PD_v1", "PD_v2", "VALUE_CHANGED"),
  cmp("MOCK-0004", "decision.result.decision", "APPROVE", "APPROVE", "SAME"),
  cmp("MOCK-0004", "model.pd.name", "PD_v1", "PD_v1", "SAME"),
  cmp("MOCK-0005", "decision.result.decision", "REJECT", "REJECT", "SAME"),
  cmp("MOCK-0005", "offer.top.amount", "", "150000", "ATTRIBUTE_NEW"),
  cmp("MOCK-0006", "decision.result.decision", "APPROVE", "APPROVE", "SAME"),
  cmp("MOCK-0006", "score.okb.value", "655", "655", "SAME"),
];

const SEGMENTS: Record<string, Json> = Object.fromEntries(
  APPS.map((app) => {
    const d = COMPARISON.find((r) => r.APP_ID === app && r.PATH === "decision.result.decision")!;
    return [app, { APP_ID: app, DECISION_BEFORE: d.VALUE_BEFORE, DECISION_AFTER: d.VALUE_AFTER, DECISION_CHANGED: d.DIFF_FLAG, PRODUCTS: "MOCK_PRODUCT" }];
  }),
);

const FACT_DIMS = ["PREFIX", "CLASS", "SUFFIX", "PATH", "ARRAY_KEY", "KEY", "VALUE_ADJUSTED", "DIFF_FLAG", "SOURCE"] as const;
type FactDims = Record<(typeof FACT_DIMS)[number], string | number>;
interface Fact {
  APP_ID: string;
  dims: FactDims;
}

const FACTS: Fact[] = COMPARISON.flatMap((r) => {
  const sides: Array<"BEFORE" | "AFTER"> = [];
  if (r.CHANGE_TYPE !== "ATTRIBUTE_NEW") sides.push("BEFORE");
  if (r.CHANGE_TYPE !== "ATTRIBUTE_LOST") sides.push("AFTER");
  return sides.map((s) => ({
    APP_ID: r.APP_ID,
    dims: {
      ...Object.fromEntries(PIVOT_DIMENSIONS.map(d => [d, SEGMENTS[r.APP_ID]?.[d] ?? null])),
      PREFIX: r.PREFIX,
      CLASS: r.CLASS,
      SUFFIX: r.SUFFIX,
      PATH: r.PATH,
      ARRAY_KEY: r.ARRAY_KEY,
      KEY: r.KEY,
      VALUE_ADJUSTED: s === "BEFORE" ? r.ADJUSTED_BEFORE : r.ADJUSTED_AFTER,
      DIFF_FLAG: r.DIFF_FLAG,
      SOURCE: s,
      CHANGE_TYPE: r.CHANGE_TYPE,
    },
  }));
});

/** Base facts like DuckDBMart.pivot(): grouped by all dims, CNT = distinct apps. */
const BASE_FACTS = (() => {
  const m = new Map<string, { dims: FactDims; apps: Set<string> }>();
  for (const f of FACTS) {
    const k = JSON.stringify(f.dims);
    const e = m.get(k) ?? { dims: f.dims, apps: new Set<string>() };
    e.apps.add(f.APP_ID);
    m.set(k, e);
  }
  return [...m.values()]
    .map((e) => ({ ...e.dims, CNT: e.apps.size }))
    .sort((a, b) => `${a.PATH}|${a.ARRAY_KEY}|${a.SOURCE}|${a.VALUE_ADJUSTED}`.localeCompare(`${b.PATH}|${b.ARRAY_KEY}|${b.SOURCE}|${b.VALUE_ADJUSTED}`));
})();

const CHECK_KIND: ScriptKind = {
  kind: "check",
  entrypoint: "CHECK = {'id', 'label', 'params', 'entrypoint': run}; run(mart, params) -> list[dict]",
  output_columns: ["LABEL", "SOURCE", "ARGUMENT", "CNT", "TOTAL", "METRIC", "APP_IDS", "RESULT", "CONFIDENCE"],
  template:
    "DEFAULTS = {}\n\ndef run(mart, params=None):\n    p = {**DEFAULTS, **(params or {})}\n    return []\n\nCHECK = {'id': 'my_check', 'label': 'My check', 'params': DEFAULTS, 'entrypoint': run}\n",
  example:
    "def run(mart, params=None):\n    total = mart.total_apps()\n    changed = mart.app_ids(diff_flag=1)\n    share = len(changed) / total if total else 0.0\n    return [{'LABEL': CHECK['label'], 'SOURCE': 'AFTER', 'ARGUMENT': 'all', 'CNT': len(changed),\n             'TOTAL': total, 'METRIC': round(share, 4), 'APP_IDS': changed[:20],\n             'RESULT': 'FAIL' if share > params['max_share'] else 'PASS',\n             'CONFIDENCE': 'HIGH' if total >= 30 else 'LOW'}]\n\nCHECK = {'id': 'changed_share', 'label': 'Share of changed apps', 'params': {'max_share': 0.5}, 'entrypoint': run}\n",
};

const BUILTIN_CHECKS: Array<[string, string, string]> = [
  ["check_ar_drop_by_product", "ar_drop_by_product", "Падение AR по продукту"],
  ["check_attribute_new_loss", "attribute_new_loss", "Изменился состав атрибутов"],
  ["check_external_score_drift", "external_score_drift", "Дрейф внешнего скора"],
  ["check_stop_factor_disappeared", "stop_factor_disappeared", "Исчез стоп-фактор"],
  ["check_target_model_changed", "target_model_changed", "Сменилась целевая модель"],
];

/** Stage → procedure slot whose code ref the mock attaches to the stage event. */
const STAGE_SLOTS: Partial<Record<(typeof RUN_STAGES)[number], string>> = { NORMALIZING: "normalize", COMPARING: "compare", AGGREGATING: "aggregate" };

// ------------------------------------------------------------- state
interface MockRun extends Run {
  _ticks: number;
  _checks: ScriptRef[];
}
interface MockCheckRun extends CheckRun {
  _ticks: number;
  _refs: ScriptRef[];
}

export function createMockFetch(opts: MockOptions) {
  const ticksPerStage = opts.ticksPerStage ?? 1;
  const custom = opts.customExecution;
  let seq = 0;
  const id = (p: string) => `${p}_mock${++seq}`;

  const datasets: Dataset[] = [
    {
      dataset_id: "ds_mock_examples",
      name: "MOCK fixture (не реальные данные)",
      shared: true,
      root: "examples",
      mode: "files",
      before: "mock_before.json",
      after: "mock_after.json",
      created_at: NOW,
      revisions: [{ revision_id: "rev_mock1", fingerprint: "mock", pairs: APPS.length, missing_before: [], missing_after: [], created_at: NOW }],
    },
  ];
  const kinds: ScriptKind[] = [
    ...PROCEDURE_SLOTS.map<ScriptKind>((k) => ({
      kind: k,
      entrypoint: `${k}(...)  # MOCK contract text`,
      output_columns: [],
      template: `def ${k}(*args, **kwargs):\n    return []\n`,
      example: `# MOCK example for ${k}\n`,
    })),
    CHECK_KIND,
  ].map((k) => ({ ...k, sources: ["builtin", "workspace", "file"], custom_execution_enabled: custom }));

  const script = (p: Partial<Script> & Pick<Script, "script_id" | "kind" | "name" | "source">): Script => ({
    filename: null,
    builtin_ref: null,
    shared: false,
    params: {},
    revision: 1,
    code_sha256: "mock000000000000",
    created_at: NOW,
    updated_at: NOW,
    ...p,
  });
  const scripts: Script[] = [
    ...PROCEDURE_SLOTS.map((k) => script({ script_id: `scr_builtin_${k}`, kind: k, source: "builtin", name: `builtin ${k} (MOCK)`, builtin_ref: `builtin:${k}`, shared: true })),
    ...BUILTIN_CHECKS.map(([file]) =>
      script({ script_id: `scr_${file}`, kind: "check", source: "builtin", name: file, filename: `${file}.py`, builtin_ref: `builtin:check:${file}.py`, shared: true }),
    ),
  ];
  const codeById = new Map<string, string>();
  const configs: Configuration[] = [];
  const runs: MockRun[] = [];
  const events = new Map<string, RunEvent[]>();
  const checkRuns: MockCheckRun[] = [];
  const reports: Report[] = [];
  const docs = new Map<string, ReportChecks>();
  const idem = new Map<string, string>();

  const scriptById = (sid: string) => scripts.find((s) => s.script_id === sid);
  const isCustom = (sid: string) => scriptById(sid)?.source !== "builtin";
  const disabled = (ids: string[]) =>
    err(403, "CUSTOM_EXECUTION_DISABLED", "Custom (workspace/file) code execution is disabled in the safe builtin-only mode; nothing was started.", {
      execution_mode: "builtin-only",
      custom_scripts: ids,
    });

  function pushEvent(run: MockRun, message: string, codeRef: string | null = null, level = "INFO", checkRunId: string | null = null) {
    const list = events.get(run.run_id) ?? [];
    list.push({
      seq: list.length + 1,
      ts: NOW,
      check_run_id: checkRunId,
      stage: run.stage,
      substep: null,
      level,
      message,
      processed: run.processed,
      total: run.total,
      code_ref: codeRef,
    });
    events.set(run.run_id, list);
  }

  function executeCheck(ref: ScriptRef, i: number): { ex: CheckExecution; rows: CheckRow[]; diag: Json[] } {
    const s = scriptById(ref.script_id)!;
    const builtin = BUILTIN_CHECKS.find(([f]) => f === s.name);
    const checkId = builtin ? builtin[1] : s.name;
    const label = builtin ? builtin[2] : s.name;
    const ex: CheckExecution = {
      execution_id: id("exe"),
      slot: `check-${String(i + 1).padStart(2, "0")}`,
      script_id: s.script_id,
      check_id: checkId,
      label,
      params: { ...(s.params ?? {}), ...(ref.params ?? {}) },
      execution_status: "SUCCEEDED",
      rows_count: 0,
      duration_seconds: 0.01,
    };
    const row = (r: Partial<CheckRow>): CheckRow => ({
      LABEL: label,
      SOURCE: "AFTER",
      ARGUMENT: "",
      CNT: 0,
      TOTAL: APPS.length,
      METRIC: 0,
      APP_IDS: [],
      RESULT: "PASS",
      CONFIDENCE: "HIGH",
      ...r,
    });
    let rows: CheckRow[] = [];
    let diag: Json[] = [];
    switch (checkId) {
      case "ar_drop_by_product":
        rows = [row({ ARGUMENT: "MOCK_PRODUCT", CNT: 2, METRIC: 0.3333, APP_IDS: ["MOCK-0003"], RESULT: "FAIL" })];
        break;
      case "attribute_new_loss":
        rows = [
          row({ SOURCE: "AFTER", ARGUMENT: "offer.top.amount", CNT: 1, METRIC: 0.1667, APP_IDS: ["MOCK-0005"], RESULT: "FAIL", CONFIDENCE: "LOW" }),
          row({ SOURCE: "BEFORE", ARGUMENT: "rules.stop.factor", CNT: 1, METRIC: 0.1667, APP_IDS: ["MOCK-0002"], RESULT: "FAIL", CONFIDENCE: "LOW" }),
        ];
        break;
      case "external_score_drift":
        ex.execution_status = "ERROR";
        diag = [{ check: checkId, error_type: "KeyError", message: "MOCK: 'SCORE_OKB_BEFORE' (имитация ошибки исполнения)" }];
        break;
      case "stop_factor_disappeared":
        rows = [row({ RESULT: "PASS" })];
        break;
      case "target_model_changed":
        rows = [];
        break;
      default: {
        const code = codeById.get(s.script_id) ?? "";
        if (/raise\s/.test(code)) {
          ex.execution_status = "ERROR";
          diag = [{ check: checkId, error_type: "RuntimeError", message: "MOCK: исключение в пользовательской проверке" }];
        } else {
          rows = [row({ ARGUMENT: "all", CNT: 3, METRIC: 0.5, APP_IDS: ["MOCK-0001", "MOCK-0003"], RESULT: "FAIL", CONFIDENCE: "LOW" })];
        }
      }
    }
    ex.rows_count = rows.length;
    return { ex, rows, diag };
  }

  function newCheckRun(run: MockRun, refs: ScriptRef[], initial: boolean): MockCheckRun {
    const crId = id("chk");
    const repId = id("rep");
    const cr: MockCheckRun = {
      check_run_id: crId,
      run_id: run.run_id,
      dataset_revision_id: "rev_mock1",
      report_id: repId,
      initial,
      status: "QUEUED",
      selected: refs.map((r) => ({ ...r })),
      executions: [],
      error: null,
      created_at: NOW,
      started_at: null,
      finished_at: null,
      links: { self: `/api/check-runs/${crId}` },
      _ticks: 0,
      _refs: refs,
    };
    checkRuns.push(cr);
    reports.push({
      report_id: repId,
      run_id: run.run_id,
      dataset_revision_id: "rev_mock1",
      check_run_id: crId,
      status: "PENDING",
      completeness: null,
      sha256: null,
      created_at: NOW,
      published_at: null,
      links: { checks: `/api/reports/${repId}/checks`, html: `/api/reports/${repId}/checks.html` },
    });
    return cr;
  }

  function finishCheckRun(cr: MockCheckRun) {
    const results = cr._refs.map(executeCheck);
    const owner = runs.find((r) => r.run_id === cr.run_id);
    if (owner && !cr.initial) {
      // like backend: check-run events land in the Run journal with check_run_id and per-slot code refs
      results.forEach((r) => pushEvent(owner, `Check ${r.ex.check_id} executed (MOCK)`, `${r.ex.slot}@mock${cr.check_run_id.slice(-6)}`, "INFO", cr.check_run_id));
    }
    cr.executions = results.map((r) => r.ex);
    cr.status = "COMPLETED";
    cr.finished_at = NOW;
    const rep = reports.find((r) => r.report_id === cr.report_id)!;
    rep.status = "PUBLISHED";
    rep.published_at = NOW;
    rep.completeness = !results.length ? "NO_CHECKS_SELECTED" : results.every((r) => r.ex.execution_status === "SUCCEEDED") ? "COMPLETE" : "INCOMPLETE";
    docs.set(rep.report_id, {
      report_id: rep.report_id,
      run_id: cr.run_id,
      check_run_id: cr.check_run_id,
      dataset_revision_id: "rev_mock1",
      completeness: rep.completeness,
      summary: { total_apps: APPS.length },
      checks: results.flatMap((r) => r.rows),
      diagnostics: results.flatMap((r) => r.diag),
      timings_seconds: Object.fromEntries(results.map((r) => [r.ex.check_id ?? r.ex.slot, r.ex.duration_seconds])),
      executions: results.map((r) => r.ex),
    });
  }

  function advanceRun(run: MockRun) {
    if (run.status === "COMPLETED" || run.status === "FAILED") return;
    run._ticks++;
    if (run.status === "QUEUED") {
      run.status = "RUNNING";
      run.stage = RUN_STAGES[0];
      run.started_at = NOW;
      pushEvent(run, "Run started (MOCK)");
      return;
    }
    if (run._ticks % ticksPerStage !== 0) return;
    const idx = RUN_STAGES.indexOf(run.stage!);
    if (idx >= 0 && idx < RUN_STAGES.length - 1) {
      run.stage = RUN_STAGES[idx + 1]!;
      const slot: string | undefined = STAGE_SLOTS[run.stage];
      if (run.stage === "NORMALIZING") run.processed = 0;
      if (run.stage === "COMPARING") run.processed = APPS.length;
      pushEvent(run, `Stage ${run.stage} (MOCK)`, slot ? `${slot}@mock00000000` : null);
      for (let i = 1; i <= (opts.extraEventsPerStage ?? 0); i++) pushEvent(run, `progress ${run.stage} ${i} (MOCK)`);
      return;
    }
    const cr = checkRuns.find((c) => c.check_run_id === run.initial_check_run_id)!;
    finishCheckRun(cr);
    run.status = "COMPLETED";
    run.finished_at = NOW;
    run.report_status = "PUBLISHED";
    run.checks_completeness = reports.find((r) => r.report_id === run.initial_report_id)!.completeness;
    pushEvent(run, "Run completed (MOCK)");
  }

  const encodeGroup = (o: unknown) => btoa(unescape(encodeURIComponent(JSON.stringify(o))));
  const decodeGroup = (s: string) => JSON.parse(decodeURIComponent(escape(atob(s)))) as { run: string; match: Record<string, unknown> };
  const matchFacts = (match: Record<string, unknown>) => {
    const out = new Set<string>();
    for (const f of FACTS) {
      const ok = Object.entries(match).every(([k, v]) => (Array.isArray(v) ? v.map(String) : [String(v)]).includes(String(f.dims[k as keyof FactDims])));
      if (ok) out.add(f.APP_ID);
    }
    return out;
  };
  const completedRun = (runId: string): MockRun | Response => {
    const run = runs.find((r) => r.run_id === runId);
    if (!run) return err(404, "NOT_FOUND", "run not found", { resource: "run", id: runId });
    if (run.status !== "COMPLETED") return err(409, "NOT_READY", "Analytics are available only after the run COMPLETED", { status: run.status });
    return run;
  };
  const strip = (run: MockRun): Run => {
    const { _ticks, _checks, ...rest } = run;
    void _ticks;
    void _checks;
    return rest;
  };
  const stripCr = (cr: MockCheckRun): CheckRun => {
    const { _ticks, _refs, ...rest } = cr;
    void _ticks;
    void _refs;
    return rest;
  };

  function createScript(kind: string, name: string, code: string, source: "workspace" | "file", filename: string | null, params: Json): Response {
    if (!kinds.some((k) => k.kind === kind)) return err(422, "SCRIPT_KIND_INVALID", "Unknown script kind");
    if (!code.trim()) return err(422, "CODE_INVALID", "Script is empty");
    if (/^\s*def\s+\w+\([^)]*$/m.test(code)) return err(422, "CODE_SYNTAX_ERROR", "Python syntax error", { line: 1, msg: "MOCK syntax check" });
    if (source === "file" && !(filename && /^[A-Za-z0-9_-]{1,80}\.py$/.test(filename))) return err(422, "SCRIPT_FILENAME_INVALID", "Uploaded file must be a plain name ending with .py");
    const s = script({ script_id: id("scr"), kind: kind as Script["kind"], source, name, filename, params, code_sha256: `mock${String(seq).padStart(12, "0")}` });
    scripts.push(s);
    codeById.set(s.script_id, code);
    return json(201, { ...s, code });
  }

  async function handle(method: string, url: URL, body: Json | undefined, form: FormData | undefined, headers: Headers): Promise<Response> {
    const p = url.pathname;
    let m: RegExpMatchArray | null;
    const idemKey = headers.get("Idempotency-Key");

    if (p === "/ready") return json(200, { ready: true, checks: [], execution_mode: custom ? "trusted-local" : "builtin-only", warnings: ["MOCK backend"] });
    if (p === "/api/session") return json(200, { authenticated: false, kind: "anonymous-session (MOCK)" });
    if (p === "/api/datasets" && method === "GET") return json(200, datasets);
    if (p === "/api/script-kinds") return json(200, kinds);
    if (p === "/api/scripts" && method === "GET") {
      const kind = url.searchParams.get("kind");
      return json(200, scripts.filter((s) => !kind || s.kind === kind));
    }
    if (p === "/api/scripts" && method === "POST") {
      const b = body ?? {};
      const extra = Object.keys(b).filter((k) => !["kind", "name", "code", "params"].includes(k));
      if (extra.length) return err(422, "VALIDATION_ERROR", "Request validation failed", { errors: extra.map((k) => ({ loc: ["body", k], type: "extra_forbidden" })) });
      return createScript(String(b.kind), String(b.name ?? ""), String(b.code ?? ""), "workspace", null, (b.params as Json) ?? {});
    }
    if (p === "/api/scripts/upload" && method === "POST") {
      if (!form) return err(422, "VALIDATION_ERROR", "multipart form expected");
      const file = form.get("file");
      if (!(file instanceof Blob)) return err(422, "VALIDATION_ERROR", "file is required");
      const fname = (file as File).name ?? null;
      return createScript(String(form.get("kind")), String(form.get("name") ?? ""), await file.text(), "file", fname, JSON.parse(String(form.get("params") ?? "{}")));
    }
    if ((m = p.match(/^\/api\/scripts\/([^/]+)$/))) {
      const s = scriptById(decodeURIComponent(m[1]!));
      if (!s) return err(404, "NOT_FOUND", "script not found", { resource: "script" });
      return json(200, { ...s, code: codeById.get(s.script_id) ?? `# MOCK builtin source of ${s.name}\n` });
    }
    if (p === "/api/configurations" && method === "GET") return json(200, configs);
    if (p === "/api/configurations" && method === "POST") {
      const b = body ?? {};
      if (!datasets.some((d) => d.dataset_id === b.dataset_id)) return err(404, "NOT_FOUND", "dataset not found", { resource: "dataset" });
      const slotsIn = (b.slots as Record<string, Partial<ScriptRef>>) ?? {};
      const slots = Object.fromEntries(PROCEDURE_SLOTS.map((k) => [k, { script_id: slotsIn[k]?.script_id ?? `scr_builtin_${k}`, params: slotsIn[k]?.params ?? null }]));
      const checks = (b.checks as ScriptRef[] | null | undefined) ?? scripts.filter((s) => s.kind === "check" && s.shared).map((s) => ({ script_id: s.script_id, params: null }));
      const c: Configuration = { config_id: id("cfg"), name: String(b.name ?? "config"), dataset_id: String(b.dataset_id), slots, checks, created_at: NOW };
      configs.push(c);
      return json(201, c);
    }
    if ((m = p.match(/^\/api\/configurations\/([^/]+)$/))) {
      const c = configs.find((x) => x.config_id === m![1]);
      return c ? json(200, c) : err(404, "NOT_FOUND", "configuration not found");
    }
    if (p === "/api/runs" && method === "POST") {
      if (!idemKey) return err(400, "IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key header (1..128 chars) for this operation");
      const replay = idem.get(`runs:${idemKey}`);
      if (replay) return json(202, strip(runs.find((r) => r.run_id === replay)!));
      const cfg = configs.find((c) => c.config_id === body?.configuration_id);
      if (!cfg) return err(404, "NOT_FOUND", "configuration not found", { resource: "configuration" });
      const used = [...Object.values(cfg.slots).map((s) => s!.script_id), ...cfg.checks.map((c) => c.script_id)];
      if (!custom && used.some(isCustom)) return disabled(used.filter(isCustom));
      const runId = id("run");
      const run: MockRun = {
        run_id: runId,
        status: "QUEUED",
        stage: null,
        substep: null,
        processed: null,
        total: APPS.length,
        config_id: cfg.config_id,
        dataset_id: cfg.dataset_id,
        dataset_revision_id: "rev_mock1",
        initial_check_run_id: "",
        initial_report_id: "",
        report_status: "PENDING",
        checks_completeness: null,
        error: null,
        created_at: NOW,
        started_at: null,
        finished_at: null,
        links: { self: `/api/runs/${runId}` },
        _ticks: 0,
        _checks: cfg.checks,
      };
      const cr = newCheckRun(run, cfg.checks, true);
      run.initial_check_run_id = cr.check_run_id;
      run.initial_report_id = cr.report_id;
      runs.unshift(run);
      idem.set(`runs:${idemKey}`, runId);
      pushEvent(run, "Run accepted (MOCK)");
      return json(202, strip(run));
    }
    if (p === "/api/runs" && method === "GET") return json(200, { items: runs.map(strip), total: runs.length, limit: 50, offset: 0 });
    if ((m = p.match(/^\/api\/runs\/([^/]+)$/))) {
      const run = runs.find((r) => r.run_id === m![1]);
      if (!run) return err(404, "NOT_FOUND", "run not found", { resource: "run" });
      advanceRun(run);
      return json(200, strip(run));
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/events$/))) {
      if (!runs.some((r) => r.run_id === m![1])) return err(404, "NOT_FOUND", "run not found");
      const after = Number(url.searchParams.get("after") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? opts.eventsPageLimit ?? 500);
      const items = (events.get(m[1]!) ?? []).filter((e) => e.seq > after).slice(0, limit);
      return json(200, { items, next_after: items.length ? items[items.length - 1]!.seq : after });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/code\/([^/]+)$/))) {
      const slot = decodeURIComponent(m[2]!);
      return json(200, { run_id: m[1], slot, script_id: `scr_builtin_${slot}`, kind: slot, source: "builtin", name: slot, script_revision: 1, code_sha256: "mock", params: {}, code: `# MOCK code snapshot for slot ${slot}\n` });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/summary$/))) {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      const changed = new Set(COMPARISON.filter((r) => r.DIFF_FLAG === 1).map((r) => r.APP_ID));
      const types: Record<string, number> = {};
      COMPARISON.forEach((r) => (types[r.CHANGE_TYPE] = (types[r.CHANGE_TYPE] ?? 0) + 1));
      const segs = Object.values(SEGMENTS);
      return json(200, {
        run_id: run.run_id,
        dataset_revision_id: run.dataset_revision_id,
        total_apps: APPS.length,
        changed_apps: changed.size,
        decision_changed_apps: segs.filter((s) => Number(s.DECISION_CHANGED) === 1).length,
        changed_attributes: COMPARISON.filter((r) => r.DIFF_FLAG === 1).length,
        change_types: types,
        approval_rate_before: segs.filter((s) => s.DECISION_BEFORE === "APPROVE").length / segs.length,
        approval_rate_after: segs.filter((s) => s.DECISION_AFTER === "APPROVE").length / segs.length,
        artifacts: [{ artifact_id: "art_mock1", kind: "comparison", rows: COMPARISON.length, bytes: 1234, sha256: "mock", created_at: NOW, download: `/api/runs/${run.run_id}/artifacts/art_mock1` }],
      });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/pivot-facts$/))) {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 1000);
      const items = BASE_FACTS.slice(offset, offset + limit);
      return json(200, { run_id: run.run_id, items, limit, offset, next_offset: items.length === limit ? offset + limit : null });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/pivot-facts\/applications$/)) && method === "POST") {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      const group = (body?.group as Record<string, unknown>) ?? {};
      if (group.SOURCE !== "BEFORE" && group.SOURCE !== "AFTER") return err(422, "PIVOT_FILTER_INVALID", "Pivot drill-down requires SOURCE BEFORE/AFTER");
      if (Object.keys(group).some((k) => !(FACT_DIMS as readonly string[]).includes(k))) return err(422, "PIVOT_FILTER_INVALID", "Unknown pivot dimension");
      const limit = Number(body?.limit ?? 200);
      const items = [...matchFacts(group)].sort().slice(0, limit);
      return json(200, { run_id: run.run_id, items, limit, total: null, total_note: "D4 port returns a limited page only; full distinct total is not provided yet" });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/pivot$/)) && method === "POST") {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      if (opts.serverPivot === false) return err(501, "ANALYTICS_UNAVAILABLE", "Server-side pivot rollup unavailable");
      return serverPivot(run, body ?? {});
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/groups\/([^/]+)\/applications$/))) {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      if (opts.serverPivot === false) return err(501, "ANALYTICS_UNAVAILABLE", "Opaque group locators unavailable");
      let g;
      try {
        g = decodeGroup(decodeURIComponent(m[2]!));
      } catch {
        return err(422, "GROUP_INVALID", "Invalid group locator");
      }
      if (g.run !== run.run_id) return err(404, "NOT_FOUND", "group not found");
      const all = [...matchFacts(g.match)].sort();
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 50);
      return json(200, { run_id: run.run_id, group: m[2], items: all.slice(offset, offset + limit), total: all.length, offset, limit });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/applications\/([^/]+)$/))) {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      const app = decodeURIComponent(m[2]!);
      if (!SEGMENTS[app]) return err(404, "NOT_FOUND", "application not found", { resource: "application" });
      return json(200, { run_id: run.run_id, segment: SEGMENTS[app], comparison: COMPARISON.filter((r) => r.APP_ID === app) });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/reports$/))) {
      const run = runs.find((r) => r.run_id === m![1]);
      if (!run) return err(404, "NOT_FOUND", "run not found");
      return json(200, { run_id: run.run_id, initial_report_id: run.initial_report_id, items: reports.filter((r) => r.run_id === run.run_id) });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/check-runs$/)) && method === "POST") {
      if (!idemKey) return err(400, "IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key header");
      const replay = idem.get(`cr:${idemKey}`);
      if (replay) return json(202, stripCr(checkRuns.find((c) => c.check_run_id === replay)!));
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      const refs = (body?.checks as ScriptRef[]) ?? [];
      for (const r of refs) {
        const s = scriptById(r.script_id);
        if (!s) return err(404, "NOT_FOUND", "script not found", { resource: "script", id: r.script_id });
        if (s.kind !== "check") return err(422, "SCRIPT_KIND_MISMATCH", "Selected script is not a check", { script_id: r.script_id });
      }
      if (new Set(refs.map((r) => r.script_id)).size !== refs.length) return err(422, "DUPLICATE_CHECK", "The same check script is selected twice");
      const customIds = refs.map((r) => r.script_id).filter(isCustom);
      if (!custom && customIds.length) return disabled(customIds);
      const cr = newCheckRun(run, refs, false);
      idem.set(`cr:${idemKey}`, cr.check_run_id);
      return json(202, stripCr(cr));
    }
    if ((m = p.match(/^\/api\/check-runs\/([^/]+)$/))) {
      const cr = checkRuns.find((c) => c.check_run_id === m![1]);
      if (!cr) return err(404, "NOT_FOUND", "check run not found");
      if (!cr.initial && cr.status !== "COMPLETED") {
        cr._ticks++;
        if (cr.status === "QUEUED") {
          cr.status = "RUNNING";
          cr.started_at = NOW;
        } else finishCheckRun(cr);
      }
      return json(200, stripCr(cr));
    }
    if ((m = p.match(/^\/api\/check-runs\/([^/]+)\/code\/([^/]+)$/))) {
      const cr = checkRuns.find((c) => c.check_run_id === m![1]);
      if (!cr) return err(404, "NOT_FOUND", "check run not found");
      const slot = decodeURIComponent(m[2]!);
      const idx = Number(slot.replace("check-", "")) - 1;
      const ref = cr._refs[idx];
      if (!slot.startsWith("check-") || !ref) return err(404, "NOT_FOUND", "code snapshot not found");
      const s = scriptById(ref.script_id)!;
      return json(200, { run_id: cr.run_id, check_run_id: cr.check_run_id, slot, script_id: s.script_id, kind: "check", source: s.source, name: s.name, script_revision: s.revision, code_sha256: s.code_sha256, params: {}, code: codeById.get(s.script_id) ?? `# MOCK builtin source of ${s.name}\n` });
    }
    if ((m = p.match(/^\/api\/reports\/([^/]+)$/))) {
      const r = reports.find((x) => x.report_id === m![1]);
      return r ? json(200, r) : err(404, "NOT_FOUND", "report not found");
    }
    if ((m = p.match(/^\/api\/reports\/([^/]+)\/checks$/))) {
      const r = reports.find((x) => x.report_id === m![1]);
      if (!r) return err(404, "NOT_FOUND", "report not found");
      if (r.status !== "PUBLISHED") return err(409, "NOT_READY", "Report is not published", { report_id: r.report_id, status: r.status });
      return json(200, docs.get(r.report_id));
    }
    return err(404, "NOT_FOUND", "Route not found");
  }

  function serverPivot(run: MockRun, b: Json): Response {
    if (Object.keys(b).some(k => !["dimensions", "filters", "limit", "offset"].includes(k)) || !Array.isArray(b.dimensions) || !b.dimensions.length || new Set(b.dimensions).size !== b.dimensions.length || (b.filters !== undefined && (!b.filters || Array.isArray(b.filters) || typeof b.filters !== "object"))) return err(422, "VALIDATION_ERROR", "Expected unique nonempty dimensions and filters object");
    const dims = b.dimensions as string[];
    const base = (b.filters ?? {}) as Record<string, unknown>;
    const limit = (b.limit ?? 100) as number;
    const offset = (b.offset ?? 0) as number;
    if (!Number.isInteger(limit) || limit < 1 || limit > 500 || !Number.isInteger(offset) || offset < 0) return err(422, "VALIDATION_ERROR", "Invalid pagination");
    for (const d of [...dims, ...Object.keys(base)]) {
      if (!(PIVOT_DIMENSIONS as readonly string[]).includes(d)) return err(422, "PIVOT_DIMENSION_INVALID", `Unknown dimension ${d}`, { allowed: PIVOT_DIMENSIONS });
    }
    const facts = FACTS.filter((f) => Object.entries(base).every(([k, v]) => (Array.isArray(v) ? v : [v]).map(String).includes(String(f.dims[k as keyof FactDims]))));
    const keyOf = (f: Fact, dims: string[]) => dims.map((d) => f.dims[d as keyof FactDims] ?? null);
    const uniq = (dims: string[]) => {
      const seen = new Map<string, Array<string | number | null>>();
      facts.forEach((f) => seen.set(JSON.stringify(keyOf(f, dims)), keyOf(f, dims)));
      return [...seen.values()].sort((a, c) => JSON.stringify(a).localeCompare(JSON.stringify(c)));
    };
    const zip = (dims: string[], vals: unknown[]) => Object.fromEntries(dims.map((d, i) => [d, vals[i]]));
    const cell = (match: Record<string, unknown>) => {
      const full = { ...base, ...match };
      return { count: matchFacts(full).size, group: encodeGroup({ run: run.run_id, match: full }) };
    };
    const items = uniq(dims).map(k => {
      const dimensions = zip(dims, k);
      const c = cell(dimensions);
      return { dimensions, cnt: c.count, group_locator: c.group };
    });
    return json(200, {
      run_id: run.run_id,
      data_revision: run.dataset_revision_id,
      items: items.slice(offset, offset + limit), total: items.length, limit, offset,
    });
  }

  return async function mockFetch(input: string, init?: RequestInit): Promise<Response> {
    const url = new URL(input, "http://mock.local");
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    let body: Json | undefined;
    let form: FormData | undefined;
    if (init?.body instanceof FormData) form = init.body;
    else if (init?.body) body = JSON.parse(String(init.body)) as Json;
    await new Promise((r) => setTimeout(r, 0));
    return handle(method, url, body, form, headers);
  };
}
