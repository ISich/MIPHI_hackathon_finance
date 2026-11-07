export type ScriptKind = 'normalize' | 'compare' | 'segments' | 'aggregate' | 'check';

export interface Dataset {
  dataset_id: string;
  name: string;
  revisions?: Array<{ revision_id: string; pairs: number }>;
}

export interface ScriptKindInfo {
  kind: ScriptKind;
  entrypoint: string;
  template: string;
  example: string;
  sources: Array<'builtin' | 'workspace' | 'file'>;
  custom_execution_enabled: boolean;
}

export interface SlotRef {
  script_id: string | null;
  params?: Record<string, unknown> | null;
}

export interface Configuration {
  config_id: string;
  name: string;
  dataset_id: string;
}

export interface Run {
  run_id: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  stage: string | null;
  substep: string | null;
  processed: number | null;
  total: number | null;
  report_status: string | null;
  error: { code?: string; message?: string } | null;
}

export interface RunEvent {
  seq: number;
  ts: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  stage: string | null;
  substep: string | null;
  message: string;
  processed: number | null;
  total: number | null;
}

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(message);
  }
}

const baseUrl = import.meta.env.VITE_API_BASE ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    credentials: 'include',
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  const payload = (await response.json().catch(() => null)) as
    | T
    | { code?: string; message?: string }
    | null;

  if (!response.ok) {
    const error = payload as { code?: string; message?: string } | null;
    throw new ApiError(response.status, error?.code ?? 'HTTP_ERROR', error?.message ?? response.statusText);
  }
  return payload as T;
}

export const api = {
  listDatasets: () => request<Dataset[]>('/api/datasets'),
  listScriptKinds: () => request<ScriptKindInfo[]>('/api/script-kinds'),
  saveScript: (input: { kind: ScriptKind; name: string; code: string }) =>
    request<{ script_id: string }>('/api/scripts', { method: 'POST', body: JSON.stringify(input) }),
  createConfiguration: (input: { name: string; dataset_id: string; slots?: Partial<Record<Exclude<ScriptKind, 'check'>, SlotRef>> }) =>
    request<Configuration>('/api/configurations', { method: 'POST', body: JSON.stringify(input) }),
  startRun: (configurationId: string) =>
    request<Run>('/api/runs', {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ configuration_id: configurationId }),
    }),
  getRun: (runId: string) => request<Run>(`/api/runs/${runId}`),
  getEvents: (runId: string, after: number) => request<{ items: RunEvent[]; next_after: number }>(`/api/runs/${runId}/events?after=${after}`),
};
