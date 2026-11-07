import { useEffect, useRef, useState } from "react";
import { slotOfCodeRef } from "../api/client";
import { api } from "../api/instance";
import { timing } from "../config";
import type { Run, RunEvent } from "../api/types";
import { RUN_STAGES } from "../api/types";
import { RunStatusBadge } from "../components/Badges";
import { Progress } from "../components/Progress";
import { ErrorView, Loading } from "../components/StateView";
import { usePolling } from "../hooks/useApi";
import { href } from "../router";
import { SummaryView } from "./SummaryView";
import { PivotView } from "./PivotView";
import { ChecksView } from "./ChecksView";
import { NewCheck } from "./NewCheck";

const TABS = [
  ["monitor", "Мониторинг"],
  ["summary", "Сводка"],
  ["pivot", "Сводная (pivot)"],
  ["checks", "Проверки"],
  ["new-check", "Новая проверка"],
] as const;
type Tab = (typeof TABS)[number][0];


/** Run monitor + report tabs. Polls status and events with ?after=seq while the Run is active. */
export function RunPage({ runId, tab, query }: { runId: string; tab: string | undefined; query: URLSearchParams }) {
  const [run, setRun] = useState<Run | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  // Default tab: summary only if the Run was already finished when opened; a Run
  // watched live stays on the monitor when it completes.
  const [openedCompleted, setOpenedCompleted] = useState<boolean | null>(null);
  const lastSeq = useRef(0);
  const current = useRef(runId);

  useEffect(() => {
    current.current = runId;
    setRun(undefined);
    setError(null);
    setEvents([]);
    setOpenedCompleted(null);
    lastSeq.current = 0;
  }, [runId]);

  const active = !run || run.status === "QUEUED" || run.status === "RUNNING";
  usePolling(
    active && !(error && !run),
    timing.runPollMs,
    async () => {
      const id = runId;
      try {
        // Status first, then events: once a terminal status is seen, the events
        // fetched afterwards already contain the final ones (polling stops then).
        const r = await api.run(id);
        const ev = await api.events(id, lastSeq.current);
        if (current.current !== id) return; // stale: user switched Run
        setRun(r);
        setOpenedCompleted((v) => (v === null ? r.status === "COMPLETED" : v));
        setError(null);
        if (ev.items.length) {
          lastSeq.current = Math.max(ev.next_after, ...ev.items.map((e) => e.seq));
          setEvents((prev) => {
            const seen = new Set(prev.map((e) => e.seq));
            return [...prev, ...ev.items.filter((e) => !seen.has(e.seq))];
          });
        }
      } catch (e) {
        if (current.current === id) setError(e);
      }
    },
    [runId],
  );

  const completed = run?.status === "COMPLETED";
  const selected: Tab = (TABS.find(([t]) => t === tab)?.[0] ?? (completed && openedCompleted ? "summary" : "monitor")) as Tab;

  return (
    <section>
      <p>
        <a href={href("runs")}>← Запуски</a>
      </p>
      <h1>
        Run <code>{runId}</code> {run ? <RunStatusBadge status={run.status} /> : null}
      </h1>
      {error && !run ? <ErrorView error={error} /> : null}
      {error && run ? <div className="muted">Ошибка обновления статуса, повторяю… </div> : null}
      {!run && !error ? <Loading what="Загрузка статуса" /> : null}
      {run ? (
        <>
          <nav className="tabs" aria-label="Разделы запуска">
            {TABS.map(([t, label]) => {
              const disabled = t !== "monitor" && !completed;
              return disabled ? (
                <span key={t} className="tab disabled" title="Отчёт доступен после завершения Run" aria-disabled="true">
                  {label}
                </span>
              ) : (
                <a key={t} className={`tab${selected === t ? " active" : ""}`} href={href("runs", runId, t)} aria-current={selected === t ? "page" : undefined}>
                  {label}
                </a>
              );
            })}
          </nav>
          {selected === "monitor" || !completed ? (
            <Monitor run={run} events={events} />
          ) : selected === "summary" ? (
            <SummaryView run={run} />
          ) : selected === "pivot" ? (
            <PivotView run={run} query={query} />
          ) : selected === "checks" ? (
            <ChecksView run={run} reportId={query.get("report")} />
          ) : (
            <NewCheck run={run} />
          )}
        </>
      ) : null}
    </section>
  );
}

function Monitor({ run, events }: { run: Run; events: RunEvent[] }) {
  const stageIdx = RUN_STAGES.indexOf(run.stage as (typeof RUN_STAGES)[number]);
  return (
    <div>
      <dl className="kv">
        <dt>Статус</dt>
        <dd data-testid="run-status">{run.status}</dd>
        <dt>Этап</dt>
        <dd data-testid="run-stage">
          {run.stage ?? "—"}
          {run.substep ? ` / ${run.substep}` : ""}
        </dd>
        <dt>Конфигурация</dt>
        <dd>{run.config_id}</dd>
        <dt>Dataset revision</dt>
        <dd>{run.dataset_revision_id}</dd>
        <dt>Initial report</dt>
        <dd>
          {run.initial_report_id} ({run.report_status ?? "—"}
          {run.checks_completeness ? `, ${run.checks_completeness}` : ""})
        </dd>
      </dl>
      <ol className="stages" aria-label="Этапы">
        {RUN_STAGES.map((s, i) => (
          <li key={s} className={i < stageIdx || run.status === "COMPLETED" ? "done" : i === stageIdx ? "current" : ""}>
            {s}
          </li>
        ))}
      </ol>
      {run.status === "RUNNING" || run.status === "QUEUED" ? <Progress processed={run.processed} total={run.total} /> : null}
      {run.status === "FAILED" ? (
        <div className="state state-error" role="alert">
          <strong>Run завершился с ошибкой (FAILED).</strong> Отчёт не публикуется.
          {run.error ? (
            <div>
              <code>{run.error.code}</code>: {run.error.message}
            </div>
          ) : null}
        </div>
      ) : null}
      {run.status !== "COMPLETED" ? <p className="muted">Отчёт станет доступен после завершения Run.</p> : null}
      <h2>Журнал</h2>
      {events.length === 0 ? <p className="muted">Событий пока нет.</p> : null}
      <table className="table" aria-label="Журнал событий">
        <tbody>
          {events.map((e) => (
            <tr key={e.seq} className={`level-${String(e.level).toLowerCase()}`}>
              <td>{e.seq}</td>
              <td>{e.ts}</td>
              <td>
                {e.stage ?? ""}
                {e.substep ? ` / ${e.substep}` : ""}
              </td>
              <td>{e.level}</td>
              <td>{e.message}</td>
              <td>{slotOfCodeRef(e.code_ref) ? <CodeLink runId={run.run_id} slot={slotOfCodeRef(e.code_ref)!} /> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Code + params snapshot actually executed for a slot (normalize|compare|segments|aggregate|check-NN). */
function CodeLink({ runId, slot }: { runId: string; slot: string }) {
  const [code, setCode] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  return (
    <details
      onToggle={(e) => {
        if ((e.currentTarget as HTMLDetailsElement).open && code === null)
          api.code(runId, slot).then((c) => setCode(`# ${c.name} [${c.source}] rev ${c.script_revision} sha256 ${c.code_sha256}\n# params: ${JSON.stringify(c.params)}\n\n${c.code}`), setErr);
      }}
    >
      <summary>код {slot}</summary>
      {err ? <ErrorView error={err} /> : code === null ? <Loading /> : <pre className="code-view">{code}</pre>}
    </details>
  );
}
