import type {
  Accepted,
  ApplicationDetail,
  ApplicationsPage,
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
  PivotRequest,
  PivotResponse,
  Readiness,
  Report,
  ReportChecks,
  Run,
  RunEvent,
  Script,
  ScriptKind,
  ScriptKindName,
  Summary,
} from "./types";

/** Machine codes the UI reacts to specifically. Everything else is shown verbatim. */
export const CODES = {
  NOT_READY: "NOT_READY",
  NOT_FOUND: "NOT_FOUND",
  CUSTOM_EXECUTION_DISABLED: "CUSTOM_EXECUTION_DISABLED",
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
    return this.code === CODES.NOT_READY || (this.status === 409 && this.code === "CONFLICT");
  }
  get isNotFound(): boolean {
    return this.status === 404;
  }
  get isForbidden(): boolean {
    return this.status === 401 || this.status === 403;
  }
  /** Custom (user) Python execution refused by backend policy (builtin-only mode). */
  get isExecutionDisabled(): boolean {
    return this.code === CODES.CUSTOM_EXECUTION_DISABLED || /EXECUTION_DISABLED/.test(this.code);
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

export class ApiClient {
  constructor(
    private readonly fetchImpl: FetchLike = (i, init) => fetch(i, init),
    private readonly base = "",
  ) {}

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const init: RequestInit = {
      method,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    };
    if (body !== undefined) {
      (init.headers as Record<string, string>)["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
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
    // /ready answers 503 with a body when not ready; surface it as data.
    return this.request<Readiness>("GET", "/ready").catch((e) => {
      if (e instanceof ApiError && e.status === 503) return { ready: false, ...e.details } as Readiness;
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
    return this.request("POST", "/api/scripts", req);
  }
  async scriptKinds(): Promise<ScriptKind[]> {
    const body = await this.request<unknown>("GET", "/api/script-kinds");
    if (body && typeof body === "object" && !Array.isArray(body) && !("items" in body)) {
      // backend may return {kind: {...}} mapping
      return Object.entries(body as Record<string, Omit<ScriptKind, "kind">>).map(([kind, v]) => ({
        ...v,
        kind: kind as ScriptKindName,
      }));
    }
    return listOf<ScriptKind>(body);
  }
  async configurations(): Promise<Configuration[]> {
    return listOf<Configuration>(await this.request("GET", "/api/configurations"));
  }
  configuration(id: string): Promise<Configuration> {
    return this.request("GET", `/api/configurations/${enc(id)}`);
  }
  createConfiguration(req: CreateConfigurationRequest): Promise<Configuration> {
    return this.request("POST", "/api/configurations", req);
  }

  // ------------------------------------------------------------ runs
  createRun(req: CreateRunRequest): Promise<Accepted> {
    return this.request("POST", "/api/runs", req);
  }
  async runs(): Promise<Run[]> {
    return listOf<Run>(await this.request("GET", "/api/runs"));
  }
  run(id: string): Promise<Run> {
    return this.request("GET", `/api/runs/${enc(id)}`);
  }
  async events(id: string, after: number): Promise<EventsPage> {
    const body = await this.request<unknown>("GET", `/api/runs/${enc(id)}/events?after=${after}`);
    const items = listOf<RunEvent>(body);
    const last = (body as { last_seq?: number }).last_seq;
    return { items, last_seq: typeof last === "number" ? last : undefined };
  }
  code(id: string, stage: string): Promise<CodeSnapshot> {
    return this.request("GET", `/api/runs/${enc(id)}/code/${enc(stage)}`);
  }

  // ------------------------------------------------------------ reporting
  summary(id: string): Promise<Summary> {
    return this.request("GET", `/api/runs/${enc(id)}/summary`);
  }
  pivot(id: string, req: PivotRequest): Promise<PivotResponse> {
    return this.request("POST", `/api/runs/${enc(id)}/pivot`, req);
  }
  groupApplications(id: string, group: string, offset: number, limit: number): Promise<ApplicationsPage> {
    return this.request(
      "GET",
      `/api/runs/${enc(id)}/groups/${enc(group)}/applications?offset=${offset}&limit=${limit}`,
    );
  }
  application(id: string, appId: string): Promise<ApplicationDetail> {
    return this.request("GET", `/api/runs/${enc(id)}/applications/${enc(appId)}`);
  }
  async reports(id: string): Promise<Report[]> {
    return listOf<Report>(await this.request("GET", `/api/runs/${enc(id)}/reports`));
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
  createCheckRun(runId: string, req: CreateCheckRunRequest): Promise<Accepted> {
    return this.request("POST", `/api/runs/${enc(runId)}/check-runs`, req);
  }
  checkRun(id: string): Promise<CheckRun> {
    return this.request("GET", `/api/check-runs/${enc(id)}`);
  }
}
