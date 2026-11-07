import type {
  ApplicationDetail,
  ApplicationsPage,
  CheckExecution,
  CheckRow,
  CheckRun,
  CodeSnapshot,
  Configuration,
  CreateCheckRunRequest,
  CreateConfigurationRequest,
  CreateRunRequest,
  CreateScriptRequest,
  Dataset,
  ErrorEnvelope,
  EventsPage,
  PivotFactsPage,
  PivotRequest,
  PivotResponse,
  Readiness,
  Report,
  ReportChecks,
  ReportList,
  Run,
  Script,
  ScriptKind,
  ScriptKindName,
  Summary,
  UploadScriptRequest,
} from "./types";

/** Machine codes the UI reacts to specifically. Everything else is shown verbatim. */
export const CODES = {
  NOT_READY: "NOT_READY",
  NOT_FOUND: "NOT_FOUND",
  CUSTOM_EXECUTION_DISABLED: "CUSTOM_EXECUTION_DISABLED",
  ANALYTICS_UNAVAILABLE: "ANALYTICS_UNAVAILABLE",
  NETWORK: "NETWORK_ERROR",
  BAD_RESPONSE: "BAD_RESPONSE",
} as const;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string;

  constructor(status: number, env: ErrorEnvelope) {
    super(env.message || env.code);
    this.name = "ApiError";
    this.status = status;
    this.code = env.code;
    this.details = env.details ?? {};
    this.requestId = env.request_id ?? "";
  }

  get isNotReady(): boolean {
    return this.code === CODES.NOT_READY;
  }
  get isNotFound(): boolean {
    return this.status === 404;
  }
  get isForbidden(): boolean {
    return (this.status === 401 || this.status === 403) && !this.isExecutionDisabled;
  }
  /** Custom (workspace/.py) Python execution refused by backend policy (builtin-only mode). */
  get isExecutionDisabled(): boolean {
    return this.code === CODES.CUSTOM_EXECUTION_DISABLED;
  }
  /** Feature not implemented by the analytics core yet (501). */
  get isUnavailable(): boolean {
    return this.code === CODES.ANALYTICS_UNAVAILABLE || this.status === 501;
  }
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

function enc(id: string): string {
  return encodeURIComponent(id);
}

/** Accept both bare arrays and {items: [...]} pages for list endpoints. */
function listOf<T>(body: unknown): T[] {
  if (Array.isArray(body)) return body as T[];
  if (body && typeof body === "object" && Array.isArray((body as { items?: unknown }).items)) {
    return (body as { items: T[] }).items;
  }
  throw new ApiError(0, { code: CODES.BAD_RESPONSE, message: "Ожидался список" });
}

export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return `ui-${c.randomUUID()}`;
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/** Slot from an event code_ref "<slot>@<sha12>". */
export function slotOfCodeRef(codeRef: string | null | undefined): string | null {
  if (!codeRef) return null;
  const slot = codeRef.split("@", 1)[0];
  return slot || null;
}

/**
 * Split a report's flat `checks` rows back into executions. The backend writes
 * rows in execution order and gives rows_count per execution; if counts do not
 * add up we refuse to guess and return null (UI then shows rows ungrouped).
 */
export function rowsByExecution(doc: ReportChecks): Array<{ ex: CheckExecution; rows: CheckRow[] }> | null {
  const total = doc.executions.reduce((n, e) => n + (e.rows_count ?? 0), 0);
  if (total !== doc.checks.length) return null;
  let i = 0;
  return doc.executions.map((ex) => {
    const rows = doc.checks.slice(i, i + ex.rows_count);
    i += ex.rows_count;
    return { ex, rows };
  });
}

interface RequestOptions {
  body?: unknown;
  form?: FormData;
  headers?: Record<string, string>;
}

export class ApiClient {
  constructor(
    private readonly fetchImpl: FetchLike = (i, init) => fetch(i, init),
    private readonly base = "",
  ) {}

  async request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) };
    const init: RequestInit = { method, credentials: "same-origin", headers };
    if (opts.form) {
      init.body = opts.form; // browser sets multipart boundary
    } else if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    let res: Response;
    try {
      res = await this.fetchImpl(this.base + path, init);
    } catch (e) {
      throw new ApiError(0, {
        code: CODES.NETWORK,
        message: "Backend недоступен: " + (e instanceof Error ? e.message : String(e)),
      });
    }
    const text = await res.text();
    let parsed: unknown = undefined;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = undefined;
      }
    }
    if (!res.ok) {
      const env = parsed as Partial<ErrorEnvelope> | undefined;
      if (env && typeof env.code === "string") {
        throw new ApiError(res.status, {
          code: env.code,
          message: String(env.message ?? env.code),
          details: env.details,
          request_id: env.request_id ?? res.headers.get("x-request-id") ?? undefined,
        });
      }
      throw new ApiError(res.status, {
        code: `HTTP_${res.status}`,
        message: `HTTP ${res.status} без стандартного error envelope`,
        request_id: res.headers.get("x-request-id") ?? undefined,
      });
    }
    if (parsed === undefined && text) {
      throw new ApiError(res.status, { code: CODES.BAD_RESPONSE, message: "Ответ не JSON" });
    }
    return parsed as T;
  }

  // ------------------------------------------------------------ system
  ready(): Promise<Readiness> {
    // /ready answers 503 with a plain body (not an error envelope) when not ready.
    return this.request<Readiness>("GET", "/ready").catch((e) => {
      if (e instanceof ApiError && e.status === 503) return { ready: false } as Readiness;
      throw e;
    });
  }

  // ------------------------------------------------------------ registry
  async datasets(): Promise<Dataset[]> {
    return listOf<Dataset>(await this.request("GET", "/api/datasets"));
  }
  async scripts(kind?: ScriptKindName): Promise<Script[]> {
    const q = kind ? `?kind=${enc(kind)}` : "";
    return listOf<Script>(await this.request("GET", `/api/scripts${q}`));
  }
  script(id: string): Promise<Script> {
    return this.request("GET", `/api/scripts/${enc(id)}`);
  }
  createScript(req: CreateScriptRequest): Promise<Script> {
    return this.request("POST", "/api/scripts", { body: req });
  }
  uploadScript(req: UploadScriptRequest): Promise<Script> {
    const form = new FormData();
    form.set("kind", req.kind);
    form.set("name", req.name);
    if (req.params) form.set("params", JSON.stringify(req.params));
    form.set("file", req.file, req.file.name);
    return this.request("POST", "/api/scripts/upload", { form });
  }
  async scriptKinds(): Promise<ScriptKind[]> {
    return listOf<ScriptKind>(await this.request("GET", "/api/script-kinds"));
  }
  async configurations(): Promise<Configuration[]> {
    return listOf<Configuration>(await this.request("GET", "/api/configurations"));
  }
  configuration(id: string): Promise<Configuration> {
    return this.request("GET", `/api/configurations/${enc(id)}`);
  }
  createConfiguration(req: CreateConfigurationRequest): Promise<Configuration> {
    return this.request("POST", "/api/configurations", { body: req });
  }

  // ------------------------------------------------------------ runs
  /** 202 + Run. The same idempotency key replays the accepted Run instead of creating a duplicate. */
  createRun(req: CreateRunRequest, idempotencyKey: string): Promise<Run> {
    return this.request("POST", "/api/runs", { body: req, headers: { "Idempotency-Key": idempotencyKey } });
  }
  async runs(): Promise<Run[]> {
    return listOf<Run>(await this.request("GET", "/api/runs"));
  }
  run(id: string): Promise<Run> {
    return this.request("GET", `/api/runs/${enc(id)}`);
  }
  events(id: string, after: number): Promise<EventsPage> {
    return this.request("GET", `/api/runs/${enc(id)}/events?after=${after}`);
  }
  code(id: string, slot: string): Promise<CodeSnapshot> {
    return this.request("GET", `/api/runs/${enc(id)}/code/${enc(slot)}`);
  }

  // ------------------------------------------------------------ reporting
  summary(id: string): Promise<Summary> {
    return this.request("GET", `/api/runs/${enc(id)}/summary`);
  }
  pivot(id: string, req: PivotRequest): Promise<PivotResponse> {
    return this.request("POST", `/api/runs/${enc(id)}/pivot`, { body: req });
  }
  groupApplications(id: string, group: string, offset: number, limit: number): Promise<ApplicationsPage> {
    return this.request(
      "GET",
      `/api/runs/${enc(id)}/groups/${enc(group)}/applications?offset=${offset}&limit=${limit}`,
    );
  }
  pivotFacts(id: string, offset: number, limit: number): Promise<PivotFactsPage> {
    return this.request("GET", `/api/runs/${enc(id)}/pivot-facts?offset=${offset}&limit=${limit}`);
  }
  pivotFactApplications(id: string, group: Record<string, unknown>, limit: number): Promise<ApplicationsPage> {
    return this.request("POST", `/api/runs/${enc(id)}/pivot-facts/applications`, { body: { group, limit } });
  }
  application(id: string, appId: string): Promise<ApplicationDetail> {
    return this.request("GET", `/api/runs/${enc(id)}/applications/${enc(appId)}`);
  }
  reports(id: string): Promise<ReportList> {
    return this.request("GET", `/api/runs/${enc(id)}/reports`);
  }
  report(reportId: string): Promise<Report> {
    return this.request("GET", `/api/reports/${enc(reportId)}`);
  }
  reportChecks(reportId: string): Promise<ReportChecks> {
    return this.request("GET", `/api/reports/${enc(reportId)}/checks`);
  }
  reportHtmlUrl(reportId: string): string {
    return `${this.base}/api/reports/${enc(reportId)}/checks.html`;
  }
  createCheckRun(runId: string, req: CreateCheckRunRequest, idempotencyKey: string): Promise<CheckRun> {
    return this.request("POST", `/api/runs/${enc(runId)}/check-runs`, {
      body: req,
      headers: { "Idempotency-Key": idempotencyKey },
    });
  }
  checkRun(id: string): Promise<CheckRun> {
    return this.request("GET", `/api/check-runs/${enc(id)}`);
  }
}
