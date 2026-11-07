import { ApiClient, type FetchLike } from "./client";

/** True only for the explicitly marked development fixture mode (vite --mode mock). */
export const IS_MOCK = import.meta.env.VITE_API_MODE === "mock";

function mockCustomExecution(): boolean {
  try {
    return window.localStorage.getItem("mock.customExecution") === "1";
  } catch {
    return false;
  }
}

let fetchImpl: FetchLike | undefined;
if (import.meta.env.VITE_API_MODE === "mock") {
  // Dynamic import: the mock is not part of a normal (real API) build at all.
  const mock = import("../mock/mockServer").then((m) => m.createMockFetch({ customExecution: mockCustomExecution(), persistSession: true }));
  fetchImpl = async (input, init) => (await mock)(input, init);
}

export const api = new ApiClient(fetchImpl, "", { bootstrapSession: true });
