// Test harness: the app's `api` singleton backed by the dev mock (test double,
// NOT the real backend). Each test may swap the mock via resetMock().
import { ApiClient, newIdempotencyKey, type FetchLike } from "../api/client";
import type { Run } from "../api/types";
import { timing } from "../config";
import { createMockFetch, type MockOptions } from "../mock/mockServer";

export const holder: { fetch: FetchLike; calls: Array<{ url: string; init?: RequestInit }> } = {
  fetch: createMockFetch({ customExecution: false }),
  calls: [],
};

export const testApi = new ApiClient((url, init) => {
  holder.calls.push({ url, init });
  return holder.fetch(url, init);
});

export function resetMock(opts: Partial<MockOptions> = {}): void {
  holder.fetch = createMockFetch({ customExecution: false, ...opts });
  holder.calls = [];
  timing.runPollMs = 5;
  timing.listPollMs = 5;
  timing.checkRunPollMs = 5;
  timing.idleJournalPollMs = 5;
}

/** Creates a config with built-ins and drives the mock Run to COMPLETED. */
export async function completedRun(): Promise<Run> {
  const cfg = await testApi.createConfiguration({ name: "t", dataset_id: "ds_mock_examples", slots: {} });
  let run = await testApi.createRun({ configuration_id: cfg.config_id }, newIdempotencyKey());
  for (let i = 0; i < 50 && run.status !== "COMPLETED"; i++) run = await testApi.run(run.run_id);
  if (run.status !== "COMPLETED") throw new Error("mock run did not complete");
  return run;
}
