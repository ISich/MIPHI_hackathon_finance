import type { Configuration, Dataset, Run, RunEvent, ScriptKindInfo } from './api';

const datasets: Dataset[] = [{
  dataset_id: 'mock-core-fixture',
  name: 'MOCK · core fixture I32554354',
  revisions: [{ revision_id: 'mock-revision-1', pairs: 1 }],
}];

const templates: Record<ScriptKindInfo['kind'], string> = {
  normalize: 'def normalize(document, app_id, source, params):\n    return []\n',
  compare: 'def compare(before_rows, after_rows, params):\n    return []\n',
  segments: "def build_segment(before_doc, after_doc, app_id, params):\n    return {'APP_ID': app_id}\n",
  aggregate: "def aggregate(comparison_rows, segments, params):\n    return {'pivot_facts': [], 'summary': {}}\n",
  check: "def run(mart, params=None):\n    return []\n\nCHECK = {'id': 'my_check', 'label': 'My check', 'params': {}, 'entrypoint': run}\n",
};

const scriptKinds = (Object.keys(templates) as ScriptKindInfo['kind'][]).map((kind) => ({
  kind,
  entrypoint: `${kind}(…, params)`,
  template: templates[kind],
  example: templates[kind],
  sources: ['builtin', 'workspace', 'file'] as ScriptKindInfo['sources'],
  custom_execution_enabled: true,
}));

const eventPlan: Array<Omit<RunEvent, 'seq' | 'ts'>> = [
  { level: 'INFO', stage: null, substep: null, message: 'Run accepted: fixture mode', processed: null, total: null },
  { level: 'INFO', stage: 'VALIDATING', substep: null, message: 'Проверка входных пар', processed: 1, total: 1 },
  { level: 'INFO', stage: 'NORMALIZING', substep: null, message: 'Нормализация 1/1 пар', processed: 1, total: 1 },
  { level: 'INFO', stage: 'COMPARING', substep: null, message: 'Сравнение 1/1 пар', processed: 1, total: 1 },
  { level: 'INFO', stage: 'AGGREGATING', substep: null, message: 'Подготовка фактов и отчёта', processed: null, total: null },
  { level: 'INFO', stage: 'CHECKING', substep: null, message: 'Исполнение проверок', processed: null, total: null },
  { level: 'INFO', stage: 'FINALIZING', substep: null, message: 'Run COMPLETED', processed: null, total: null },
];

let counter = 0;
const startedAt = new Map<string, number>();

function state(runId: string): Run {
  const elapsed = Math.floor((Date.now() - (startedAt.get(runId) ?? Date.now())) / 850);
  const item = eventPlan[Math.min(elapsed, eventPlan.length - 1)];
  return {
    run_id: runId,
    status: elapsed >= eventPlan.length - 1 ? 'COMPLETED' : elapsed === 0 ? 'QUEUED' : 'RUNNING',
    stage: item.stage,
    substep: item.substep,
    processed: item.processed,
    total: item.total,
    report_status: elapsed >= eventPlan.length - 1 ? 'PUBLISHED' : 'PENDING',
    error: null,
  };
}

export const mockApi = {
  listDatasets: async () => datasets,
  listScriptKinds: async () => scriptKinds,
  saveScript: async () => ({ script_id: `mock-script-${++counter}` }),
  createConfiguration: async (input: { name: string; dataset_id: string }): Promise<Configuration> => ({
    config_id: `mock-config-${++counter}`,
    name: input.name,
    dataset_id: input.dataset_id,
  }),
  startRun: async (): Promise<Run> => {
    const runId = `mock-run-${++counter}`;
    startedAt.set(runId, Date.now());
    return state(runId);
  },
  getRun: async (runId: string) => state(runId),
  getEvents: async (runId: string, after: number) => {
    const elapsed = Math.min(Math.floor((Date.now() - (startedAt.get(runId) ?? Date.now())) / 850), eventPlan.length - 1);
    const items = eventPlan.slice(after, elapsed + 1).map((event, index) => ({
      ...event,
      seq: after + index + 1,
      ts: new Date().toISOString(),
    }));
    return { items, next_after: after + items.length };
  },
};
