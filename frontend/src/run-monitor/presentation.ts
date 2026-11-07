import type { Run } from "../api/types";

export type RunFilter = "all" | "active" | "completed" | "failed";

export function selectRuns(runs: Run[], query: string, filter: RunFilter): Run[] {
  const term = query.trim().toLocaleLowerCase("ru");
  return runs.filter(run => {
    const matchesStatus = filter === "all" || (filter === "active" && (run.status === "RUNNING" || run.status === "QUEUED")) || (filter === "completed" && run.status === "COMPLETED") || (filter === "failed" && run.status === "FAILED");
    return matchesStatus && `${run.run_id} ${run.config_id} ${run.dataset_id} ${run.status} ${run.stage ?? ""}`.toLocaleLowerCase("ru").includes(term);
  }).sort((first, second) => Date.parse(second.created_at) - Date.parse(first.created_at) || first.run_id.localeCompare(second.run_id));
}

export function activityByDay(runs: Run[], now: Date, days = 7) {
  return Array.from({ length: days }, (_, index) => {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - days + index + 1);
    const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1);
    return {
      label: start.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }),
      count: runs.filter(run => { const time = Date.parse(run.created_at); return time >= start.getTime() && time < end.getTime(); }).length,
    };
  });
}

export function formatRunDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function formatDuration(run: Run) {
  if (!run.started_at || !run.finished_at) return "—";
  const seconds = Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  return seconds < 60 ? `${seconds} с` : `${Math.floor(seconds / 60)} мин ${seconds % 60} с`;
}
