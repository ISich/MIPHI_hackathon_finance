import type { ExecutionStatus, RunStatus } from "../api/types";

export function RunStatusBadge({ status }: { status: RunStatus | string }) {
  return <span className={`badge badge-${String(status).toLowerCase()}`}>{status}</span>;
}

export function ResultBadge({ result, low }: { result: "PASS" | "FAIL"; low: boolean }) {
  return (
    <span className={`badge badge-${result.toLowerCase()}${low ? " badge-low" : ""}`} title={low ? "LOW confidence" : "HIGH confidence"}>
      {result}
      {low ? " · LOW" : ""}
    </span>
  );
}

export function ExecBadge({ status }: { status: ExecutionStatus }) {
  const ok = status === "SUCCEEDED";
  return (
    <span className={`badge ${ok ? "badge-exec-ok" : "badge-exec-error"}`}>
      {ok ? "исполнена" : `ошибка исполнения: ${status}`}
    </span>
  );
}
