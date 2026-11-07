// =============================================================================
// DEVELOPMENT-ONLY MOCK BACKEND. NOT A REAL CALCULATION.
//
// Implements the same HTTP wire contract as ApiClient expects, as a `fetch`
// replacement, so the real client/parsing code path is exercised. All data is
// synthetic (APP_ID "MOCK-…"), numbers are NOT produced by decision_diff and
// must never be shown as results. Enabled only by VITE_API_MODE=mock, and the
// UI then shows a permanent MOCK banner.
// =============================================================================
import type {
  CheckExecution,
  CheckRow,
  ComparisonRow,
  Configuration,
  Dataset,
  Report,
  Run,
  RunEvent,
  Script,
  ScriptKind,
  ScriptRef,
} from "../api/types";
import { RUN_STAGES, PROCEDURE_SLOTS } from "../api/types";

export interface MockOptions {
  /** Mirrors backend DD_EXECUTION_MODE: false = builtin-only (backend default). */
  customExecution: boolean;
  /** How many GET polls a run/check-run needs per stage. */
  ticksPerStage?: number;
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

function cmp(
  app: string,
  path: string,
  before: string,
  after: string,
  type: ComparisonRow["CHANGE_TYPE"],
  arrayKey = "",
): ComparisonRow {
  const parts = path.split(".");
  return {
    APP_ID: app,
    PREFIX: parts[0] ?? "",
    CLASS: parts[1] ?? "",
    SUFFIX: parts.slice(2).join(".") || "",
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
    return [
      app,
      {
        APP_ID: app,
        DECISION_BEFORE: d.VALUE_BEFORE,
        DECISION_AFTER: d.VALUE_AFTER,
        DECISION_CHANGED: d.DIFF_FLAG,
        PRODUCTS: "MOCK_PRODUCT",
      },
    ];
  }),
);

interface Fact {
  APP_ID: string;
  dims: Record<string, string | number>;
}

const FACTS: Fact[] = COMPARISON.flatMap((r) => {
  const sides: Array<"BEFORE" | "AFTER"> = [];
  if (r.CHANGE_TYPE !== "ATTRIBUTE_NEW") sides.push("BEFORE");
  if (r.CHANGE_TYPE !== "ATTRIBUTE_LOST") sides.push("AFTER");
  return sides.map((s) => ({
    APP_ID: r.APP_ID,
    dims: {
      PREFIX: r.PREFIX,
      CLASS: r.CLASS,
      SUFFIX: r.SUFFIX,
      PATH: r.PATH,
      ARRAY_KEY: r.ARRAY_KEY,
      KEY: r.KEY,
      VALUE_ADJUSTED: s === "BEFORE" ? r.ADJUSTED_BEFORE : r.ADJUSTED_AFTER,
      SOURCE: s,
      DIFF_FLAG: r.DIFF_FLAG,
      CHANGE_TYPE: r.CHANGE_TYPE,
      DECISION_CHANGED: Number(SEGMENTS[r.APP_ID]!.DECISION_CHANGED),
    },
  }));
});

const PIVOT_DIMS = Object.keys(FACTS[0]!.dims);

const CHECK_KIND: ScriptKind = {
  kind: "check",
  entrypoint: "CHECK = {'id', 'label', 'params', 'entrypoint': run}; run(mart, params) -> list[dict]",
  output_columns: ["LABEL", "SOURCE", "ARGUMENT", "CNT", "TOTAL", "METRIC", "APP_IDS", "RESULT", "CONFIDENCE"],
  template:
    "DEFAULTS = {}\n\ndef run(mart, params=None):\n    p = {**DEFAULTS, **(params or {})}\n    return []\n\nCHECK = {'id': 'my_check', 'label': 'My check', 'params': DEFAULTS, 'entrypoint': run}\n",
  example:
    "def run(mart, params=None):\n    total = mart.total_apps()\n    changed = mart.app_ids(diff_flag=1)\n    return [{'LABEL': CHECK['label'], 'SOURCE': 'AFTER', 'ARGUMENT': 'all', 'CNT': len(changed), 'TOTAL': total,\n             'METRIC': len(changed) / total, 'APP_IDS': changed[:20], 'RESULT': 'PASS', 'CONFIDENCE': 'LOW'}]\n\nCHECK = {'id': 'changed_share', 'label': 'Share of changed apps', 'params': {}, 'entrypoint': run}\n",
};

const PROC_KINDS: ScriptKind[] = PROCEDURE_SLOTS.map((k) => ({
  kind: k,
  entrypoint: `${k}(...)  # mock contract text`,
  output_columns: [],
  template: `def ${k}(*args, **kwargs):\n    return []\n`,
  example: `# example for ${k}\n`,
}));

const BUILTIN_CHECKS: Array<[string, string]> = [
  ["check_ar_drop_by_product", "Падение AR по продукту"],
  ["check_attribute_new_loss", "Изменился состав атрибутов"],
  ["check_external_score_drift", "Дрейф внешнего скора"],
  ["check_stop_factor_disappeared", "Исчез стоп-фактор"],
  ["check_target_model_changed", "Сменилась целевая модель"],
];

// ------------------------------------------------------------- state
interface MockRun extends Run {
  _ticks: number;
  _customProcedure: boolean;
}
interface MockCheckRun {
  check_run_id: string;
  run_id: string;
  report_id: string;
  checks: ScriptRef[];
  status: string;
  _ticks: number;
  created_at: string;
}

export function createMockFetch(opts: MockOptions) {
  const ticksPerStage = opts.ticksPerStage ?? 1;
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
      revisions: [
        {
          revision_id: "rev_mock1",
          fingerprint: "mock",
          pairs: APPS.length,
          missing_before: [],
          missing_after: [],
          created_at: NOW,
        },
      ],
    },
  ];

  const scripts: Script[] = [
    ...PROCEDURE_SLOTS.map<Script>((k) => ({
      script_id: `scr_builtin_${k}`,
      kind: k,
      source: "builtin",
      name: `builtin ${k} (mock)`,
      filename: null,
      builtin_ref: `builtin:${k}`,
      shared: true,
      params: {},
      revision: 1,
      code_sha256: "mock",
      created_at: NOW,
      updated_at: NOW,
    })),
    ...BUILTIN_CHECKS.map<Script>(([name]) => ({
      script_id: `scr_${name}`,
      kind: "check",
      source: "builtin",
      name,
      filename: `${name}.py`,
      builtin_ref: `builtin:check:${name}.py`,
      shared: true,
      params: {},
      revision: 1,
      code_sha256: "mock",
      created_at: NOW,
      updated_at: NOW,
    })),
  ];
  const codeById = new Map<string, string>();
  const configs: Configuration[] = [];
  const runs: MockRun[] = [];
  const events = new Map<string, RunEvent[]>();
  const checkRuns: MockCheckRun[] = [];
  const reports: Report[] = [];
  const reportExecutions = new Map<string, CheckExecution[]>();

  const isCustom = (sid: string) => scripts.find((s) => s.script_id === sid)?.source !== "builtin";

  function pushEvent(run: MockRun, level: string, message: string) {
    const list = events.get(run.run_id) ?? [];
    list.push({
      seq: list.length + 1,
      run_id: run.run_id,
      stage: run.stage,
      level,
      message,
      processed: run.processed ?? null,
      total: run.total ?? null,
      ts: NOW,
      code_ref: run.stage ? `/api/runs/${run.run_id}/code/${run.stage}` : null,
    });
    events.set(run.run_id, list);
  }

  function executeCheck(ref: ScriptRef): CheckExecution {
    const s = scripts.find((x) => x.script_id === ref.script_id)!;
    const base = {
      execution_id: id("exe"),
      check_id: s.name,
      script_id: s.script_id,
      label: s.name,
      params: { ...(s.params ?? {}), ...(ref.params ?? {}) },
      duration_s: 0.01,
    };
    const row = (r: Partial<CheckRow>): CheckRow => ({
      LABEL: s.name,
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
    switch (s.name) {
      case "check_ar_drop_by_product":
        return { ...base, execution_status: "SUCCESS", rows: [row({ ARGUMENT: "MOCK_PRODUCT", CNT: 2, METRIC: 0.3333, APP_IDS: ["MOCK-0003"], RESULT: "FAIL", CONFIDENCE: "HIGH" })] };
      case "check_attribute_new_loss":
        return {
          ...base,
          execution_status: "SUCCESS",
          rows: [
            row({ SOURCE: "AFTER", ARGUMENT: "offer.top.amount", CNT: 1, METRIC: 0.1667, APP_IDS: ["MOCK-0005"], RESULT: "FAIL", CONFIDENCE: "LOW" }),
            row({ SOURCE: "BEFORE", ARGUMENT: "rules.stop.factor", CNT: 1, METRIC: 0.1667, APP_IDS: ["MOCK-0002"], RESULT: "FAIL", CONFIDENCE: "LOW" }),
          ],
        };
      case "check_external_score_drift":
        return { ...base, execution_status: "ERROR", rows: [], diagnostics: { error_type: "KeyError", message: "MOCK: 'SCORE_OKB_BEFORE' (имитация ошибки исполнения)" } };
      case "check_stop_factor_disappeared":
        return { ...base, execution_status: "SUCCESS", rows: [row({ ARGUMENT: "", RESULT: "PASS" })] };
      case "check_target_model_changed":
        return { ...base, execution_status: "SUCCESS", rows: [] };
      default: {
        const code = codeById.get(s.script_id) ?? "";
        if (/raise\s/.test(code)) {
          return { ...base, execution_status: "ERROR", rows: [], diagnostics: { error_type: "RuntimeError", message: "MOCK: исключение в пользовательской проверке" } };
        }
        return { ...base, execution_status: "SUCCESS", rows: [row({ ARGUMENT: "all", CNT: 3, METRIC: 0.5, APP_IDS: ["MOCK-0001", "MOCK-0003"], RESULT: "FAIL", CONFIDENCE: "LOW" })] };
      }
    }
  }

  function makeReport(runId: string, checkRunId: string, initial: boolean, checks: ScriptRef[]): Report {
    const r: Report = {
      report_id: id("rep"),
      run_id: runId,
      data_revision: "rev_mock1",
      check_run_id: checkRunId,
      status: "PENDING",
      created_at: NOW,
      is_initial: initial,
    };
    reports.push(r);
    reportExecutions.set(r.report_id, checks.map(executeCheck));
    return r;
  }

  function advanceRun(run: MockRun) {
    if (run.status === "COMPLETED" || run.status === "FAILED") return;
    run._ticks++;
    if (run.status === "QUEUED") {
      run.status = "RUNNING";
      run.stage = RUN_STAGES[0];
      run.started_at = NOW;
      pushEvent(run, "INFO", "Run started (MOCK)");
      return;
    }
    if (run._ticks % ticksPerStage !== 0) return;
    const idx = RUN_STAGES.indexOf(run.stage as (typeof RUN_STAGES)[number]);
    if (run.stage === "NORMALIZING") {
      run.processed = APPS.length;
    }
    if (idx >= 0 && idx < RUN_STAGES.length - 1) {
      run.stage = RUN_STAGES[idx + 1]!;
      pushEvent(run, "INFO", `Stage ${run.stage} (MOCK)`);
      if (run.stage === "NORMALIZING") run.processed = 0;
      return;
    }
    // finalize
    const cfg = configs.find((c) => c.config_id === run.config_id)!;
    const crId = id("chk");
    const rep = makeReport(run.run_id, crId, true, cfg.checks);
    rep.status = "READY";
    checkRuns.push({ check_run_id: crId, run_id: run.run_id, report_id: rep.report_id, checks: cfg.checks, status: "COMPLETED", _ticks: 0, created_at: NOW });
    run.initial_report_id = rep.report_id;
    run.status = "COMPLETED";
    run.finished_at = NOW;
    pushEvent(run, "INFO", "Run completed (MOCK)");
  }

  function advanceCheckRun(cr: MockCheckRun) {
    if (cr.status === "COMPLETED") return;
    cr._ticks++;
    if (cr.status === "QUEUED") cr.status = "RUNNING";
    else {
      cr.status = "COMPLETED";
      reports.find((r) => r.report_id === cr.report_id)!.status = "READY";
    }
  }

  const encodeGroup = (o: unknown) => btoa(unescape(encodeURIComponent(JSON.stringify(o))));
  const decodeGroup = (s: string) => JSON.parse(decodeURIComponent(escape(atob(s)))) as { run: string; match: Record<string, unknown> };

  function matchFacts(match: Record<string, unknown>): Set<string> {
    const out = new Set<string>();
    for (const f of FACTS) {
      let ok = true;
      for (const [k, v] of Object.entries(match)) {
        const allowed = Array.isArray(v) ? v.map(String) : [String(v)];
        if (!allowed.includes(String(f.dims[k]))) {
          ok = false;
          break;
        }
      }
      if (ok) out.add(f.APP_ID);
    }
    return out;
  }

  function completedRun(runId: string): MockRun | Response {
    const run = runs.find((r) => r.run_id === runId);
    if (!run) return err(404, "NOT_FOUND", "run not found", { resource: "run", id: runId });
    if (run.status !== "COMPLETED") return err(409, "NOT_READY", "Run is not completed yet", { status: run.status });
    return run;
  }

  async function handle(method: string, url: URL, body: Json | undefined): Promise<Response> {
    const p = url.pathname;
    let m: RegExpMatchArray | null;

    if (p === "/ready") return json(200, { ready: true, execution_mode: opts.customExecution ? "trusted-local" : "builtin-only", mock: true });
    if (p === "/api/datasets" && method === "GET") return json(200, datasets);
    if (p === "/api/script-kinds") return json(200, [...PROC_KINDS, CHECK_KIND]);
    if (p === "/api/scripts" && method === "GET") {
      const kind = url.searchParams.get("kind");
      return json(200, scripts.filter((s) => !kind || s.kind === kind));
    }
    if (p === "/api/scripts" && method === "POST") {
      const b = body ?? {};
      const code = String(b.code ?? "");
      if (!code.trim()) return err(422, "CODE_INVALID", "Script is empty");
      if (/^\s*def\s+\w+\([^)]*$/m.test(code)) return err(422, "CODE_SYNTAX_ERROR", "Python syntax error", { line: 1, msg: "MOCK syntax check" });
      const s: Script = {
        script_id: id("scr"),
        kind: b.kind as Script["kind"],
        source: b.source as Script["source"],
        name: String(b.name ?? "unnamed"),
        filename: (b.filename as string) ?? null,
        builtin_ref: null,
        shared: false,
        params: (b.params as Json) ?? {},
        revision: 1,
        code_sha256: `mock${seq}`,
        created_at: NOW,
        updated_at: NOW,
      };
      scripts.push(s);
      codeById.set(s.script_id, code);
      return json(201, { ...s, code });
    }
    if ((m = p.match(/^\/api\/scripts\/([^/]+)$/))) {
      const s = scripts.find((x) => x.script_id === decodeURIComponent(m![1]!));
      if (!s) return err(404, "NOT_FOUND", "script not found");
      return json(200, { ...s, code: codeById.get(s.script_id) ?? `# MOCK builtin source of ${s.name}\n` });
    }
    if (p === "/api/configurations" && method === "GET") return json(200, configs);
    if (p === "/api/configurations" && method === "POST") {
      const b = body ?? {};
      if (!datasets.some((d) => d.dataset_id === b.dataset_id)) return err(404, "NOT_FOUND", "dataset not found");
      const slotsIn = (b.slots as Record<string, ScriptRef>) ?? {};
      const slots = Object.fromEntries(
        PROCEDURE_SLOTS.map((k) => [k, { script_id: slotsIn[k]?.script_id ?? `scr_builtin_${k}`, params: slotsIn[k]?.params ?? null }]),
      ) as Configuration["slots"];
      const checks = (b.checks as ScriptRef[] | null | undefined) ?? scripts.filter((s) => s.kind === "check" && s.shared).map((s) => ({ script_id: s.script_id }));
      const c: Configuration = { config_id: id("cfg"), name: String(b.name ?? "config"), dataset_id: String(b.dataset_id), slots, checks, created_at: NOW };
      configs.push(c);
      return json(201, c);
    }
    if ((m = p.match(/^\/api\/configurations\/([^/]+)$/))) {
      const c = configs.find((x) => x.config_id === m![1]);
      return c ? json(200, c) : err(404, "NOT_FOUND", "configuration not found");
    }
    if (p === "/api/runs" && method === "POST") {
      const cfg = configs.find((c) => c.config_id === body?.config_id);
      if (!cfg) return err(404, "NOT_FOUND", "configuration not found");
      const custom = [...Object.values(cfg.slots).map((s) => s.script_id), ...cfg.checks.map((c) => c.script_id)].some(isCustom);
      if (custom && !opts.customExecution) {
        return err(403, "CUSTOM_EXECUTION_DISABLED", "Custom Python execution is disabled on this server (DD_EXECUTION_MODE=builtin-only)", { execution_mode: "builtin-only" });
      }
      const run: MockRun = {
        run_id: id("run"),
        config_id: cfg.config_id,
        dataset_id: cfg.dataset_id,
        data_revision: "rev_mock1",
        status: "QUEUED",
        stage: null,
        processed: null,
        total: APPS.length,
        created_at: NOW,
        initial_report_id: null,
        _ticks: 0,
        _customProcedure: custom,
      };
      runs.unshift(run);
      pushEvent(run, "INFO", "Run accepted (MOCK)");
      return json(202, { run_id: run.run_id, status: "QUEUED", status_url: `/api/runs/${run.run_id}` });
    }
    if (p === "/api/runs" && method === "GET") return json(200, runs.map(strip));
    if ((m = p.match(/^\/api\/runs\/([^/]+)$/))) {
      const run = runs.find((r) => r.run_id === m![1]);
      if (!run) return err(404, "NOT_FOUND", "run not found");
      advanceRun(run);
      return json(200, strip(run));
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/events$/))) {
      if (!runs.some((r) => r.run_id === m![1])) return err(404, "NOT_FOUND", "run not found");
      const after = Number(url.searchParams.get("after") ?? 0);
      const items = (events.get(m[1]!) ?? []).filter((e) => e.seq > after);
      return json(200, { items, last_seq: items.length ? items[items.length - 1]!.seq : after });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/code\/([^/]+)$/))) {
      return json(200, { run_id: m[1], stage: m[2], code: `# MOCK code snapshot for stage ${m[2]}\n` });
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
        data_revision: run.data_revision,
        total_apps: APPS.length,
        changed_apps: changed.size,
        decision_changed_apps: segs.filter((s) => Number(s.DECISION_CHANGED) === 1).length,
        changed_attributes: COMPARISON.filter((r) => r.DIFF_FLAG === 1).length,
        change_types: types,
        approval_rate_before: segs.filter((s) => s.DECISION_BEFORE === "APPROVE").length / segs.length,
        approval_rate_after: segs.filter((s) => s.DECISION_AFTER === "APPROVE").length / segs.length,
        top_paths: [
          { path: "decision.result.decision", changed_apps: 2 },
          { path: "score.okb.value", changed_apps: 1 },
        ],
        completeness: { pairs_total: APPS.length, pairs_failed: 0 },
      });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/pivot$/)) && method === "POST") {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      const b = (body ?? {}) as { rows?: string[]; cols?: string[]; filters?: Array<{ dim: string; op: string; values: unknown[] }> };
      const rows = b.rows ?? [];
      const cols = b.cols ?? [];
      for (const d of [...rows, ...cols, ...(b.filters ?? []).map((f) => f.dim)]) {
        if (!PIVOT_DIMS.includes(d)) return err(422, "PIVOT_DIMENSION_INVALID", `Unknown dimension ${d}`, { allowed: PIVOT_DIMS });
      }
      const base: Record<string, unknown> = {};
      for (const f of b.filters ?? []) base[f.dim] = f.values;
      const facts = FACTS.filter((f) => Object.entries(base).every(([k, v]) => (v as unknown[]).map(String).includes(String(f.dims[k]))));
      const keyOf = (f: Fact, dims: string[]) => dims.map((d) => f.dims[d] ?? null);
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
      const rowKeys = uniq(rows);
      const colKeys = uniq(cols);
      const cells = [];
      for (const rk of rowKeys)
        for (const ck of colKeys) {
          const c = cell({ ...zip(rows, rk), ...zip(cols, ck) });
          if (c.count > 0) cells.push({ row: rk, col: ck, ...c });
        }
      return json(200, {
        run_id: run.run_id,
        data_revision: run.data_revision,
        rows,
        cols,
        cells,
        row_totals: rowKeys.map((k) => ({ key: k, ...cell(zip(rows, k)) })),
        col_totals: colKeys.map((k) => ({ key: k, ...cell(zip(cols, k)) })),
        grand_total: cell({}),
      });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/groups\/([^/]+)\/applications$/))) {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
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
      if (!SEGMENTS[app]) return err(404, "NOT_FOUND", "application not found");
      return json(200, { run_id: run.run_id, app_id: app, segment: SEGMENTS[app], comparison: COMPARISON.filter((r) => r.APP_ID === app) });
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/reports$/))) {
      if (!runs.some((r) => r.run_id === m![1])) return err(404, "NOT_FOUND", "run not found");
      return json(200, reports.filter((r) => r.run_id === m![1]));
    }
    if ((m = p.match(/^\/api\/runs\/([^/]+)\/check-runs$/)) && method === "POST") {
      const run = completedRun(m[1]!);
      if (run instanceof Response) return run;
      const checks = ((body?.checks as ScriptRef[]) ?? []).filter((c) => scripts.some((s) => s.script_id === c.script_id && s.kind === "check"));
      if (!checks.length) return err(422, "VALIDATION_ERROR", "No checks selected");
      if (checks.some((c) => isCustom(c.script_id)) && !opts.customExecution) {
        return err(403, "CUSTOM_EXECUTION_DISABLED", "Custom Python execution is disabled on this server (DD_EXECUTION_MODE=builtin-only)", { execution_mode: "builtin-only" });
      }
      const crId = id("chk");
      const rep = makeReport(run.run_id, crId, false, checks);
      checkRuns.push({ check_run_id: crId, run_id: run.run_id, report_id: rep.report_id, checks, status: "QUEUED", _ticks: 0, created_at: NOW });
      return json(202, { check_run_id: crId, report_id: rep.report_id, status: "QUEUED", status_url: `/api/check-runs/${crId}` });
    }
    if ((m = p.match(/^\/api\/check-runs\/([^/]+)$/))) {
      const cr = checkRuns.find((c) => c.check_run_id === m![1]);
      if (!cr) return err(404, "NOT_FOUND", "check run not found");
      advanceCheckRun(cr);
      const { _ticks: _t, ...rest } = cr;
      void _t;
      return json(200, { ...rest, data_revision: "rev_mock1" });
    }
    if ((m = p.match(/^\/api\/reports\/([^/]+)$/))) {
      const r = reports.find((x) => x.report_id === m![1]);
      return r ? json(200, r) : err(404, "NOT_FOUND", "report not found");
    }
    if ((m = p.match(/^\/api\/reports\/([^/]+)\/checks$/))) {
      const r = reports.find((x) => x.report_id === m![1]);
      if (!r) return err(404, "NOT_FOUND", "report not found");
      if (r.status !== "READY") return err(409, "NOT_READY", "Report is not ready", { status: r.status });
      return json(200, { report_id: r.report_id, run_id: r.run_id, check_run_id: r.check_run_id, status: r.status, executions: reportExecutions.get(r.report_id) ?? [] });
    }
    return err(404, "NOT_FOUND", "Route not found (mock)");
  }

  function strip(run: MockRun): Run {
    const { _ticks: _a, _customProcedure: _b, ...rest } = run;
    void _a;
    void _b;
    return rest;
  }

  return async function mockFetch(input: string, init?: RequestInit): Promise<Response> {
    const url = new URL(input, "http://mock.local");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Json) : undefined;
    await new Promise((r) => setTimeout(r, 0));
    return handle(method, url, body);
  };
}
