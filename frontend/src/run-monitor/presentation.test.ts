import { describe, expect, it } from "vitest";
import type { Run } from "../api/types";
import { activityByDay, formatDuration, formatRunDate, selectRuns } from "./presentation";

const run = (changes: Partial<Run>): Run => ({
  run_id: "run_a", status: "COMPLETED", stage: "FINALIZING", processed: 6, total: 6, config_id: "cfg_main", dataset_id: "ds_examples", dataset_revision_id: "rev_1", initial_check_run_id: "cr_1", initial_report_id: "rep_1", report_status: null, checks_completeness: null, error: null, created_at: "2026-11-07T08:00:00Z", started_at: null, finished_at: null, links: {}, ...changes,
});

describe("run list presentation", () => {
  const records = [run({ run_id: "run_old", created_at: "2026-11-06T08:00:00Z" }), run({ run_id: "run_active", status: "RUNNING" }), run({ run_id: "run_queued", status: "QUEUED" }), run({ run_id: "run_failed", status: "FAILED", dataset_id: "ds_test" })];
  it("filters both active statuses without changing source data", () => {
    expect(selectRuns(records, "", "active").map(item => item.run_id)).toEqual(["run_active", "run_queued"]);
    expect(records[0]?.run_id).toBe("run_old");
  });
  it("combines case-insensitive search with status and sorts newest first", () => {
    expect(selectRuns(records, "  DS_TEST ", "failed").map(item => item.run_id)).toEqual(["run_failed"]);
    expect(selectRuns(records, "run_failed", "completed")).toEqual([]);
    expect(selectRuns(records, "", "all").at(-1)?.run_id).toBe("run_old");
  });
  it("groups by local calendar day, excluding invalid, older and future dates", () => {
    const now = new Date(2026, 10, 7, 12);
    const data = [run({ created_at: new Date(2026, 10, 7, 0).toISOString() }), run({ created_at: new Date(2026, 10, 6, 23, 59).toISOString() }), run({ created_at: new Date(2026, 10, 1, 0).toISOString() }), run({ created_at: new Date(2026, 9, 31, 23, 59).toISOString() }), run({ created_at: new Date(2026, 10, 8, 0).toISOString() }), run({ created_at: "invalid" })];
    expect(activityByDay(data, now).map(day => day.count)).toEqual([1, 0, 0, 0, 0, 1, 1]);
    expect(activityByDay([], now).every(day => day.count === 0)).toBe(true);
  });
  it("uses calendar boundaries across daylight saving transitions", () => {
    const now = new Date(2026, 2, 9, 12);
    const data = [run({ created_at: new Date(2026, 2, 8, 23, 59).toISOString() }), run({ created_at: new Date(2026, 2, 9, 0).toISOString() })];
    expect(activityByDay(data, now, 2).map(day => day.count)).toEqual([1, 1]);
  });
  it("does not invent duration for an unfinished or invalid run", () => {
    expect(formatDuration(run({}))).toBe("—");
    expect(formatDuration(run({ started_at: "invalid", finished_at: "2026-11-07T08:00:00Z" }))).toBe("—");
    expect(formatDuration(run({ started_at: "2026-11-07T08:00:00Z", finished_at: "2026-11-07T08:01:05Z" }))).toBe("1 мин 5 с");
    expect(formatDuration(run({ started_at: "2026-11-07T08:01:00Z", finished_at: "2026-11-07T08:00:00Z" }))).toBe("—");
    expect(formatRunDate("invalid")).toBe("—");
  });
});
