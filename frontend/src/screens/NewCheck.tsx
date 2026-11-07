import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/instance";
import type { CheckRun, Run, ScriptRef } from "../api/types";
import { PythonEditor } from "../components/PythonEditor";
import { Async, ErrorView } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href, navigate } from "../router";
import { ExecutionModeNote } from "./Workspace";

export const CHECK_POLL_MS = 1500;

/**
 * "New check" scenario: editor or .py upload → POST /api/scripts (immutable
 * snapshot) → POST /api/runs/{id}/check-runs with the Run's full check set
 * plus the new one → poll check-run → open the returned report_id.
 */
export function NewCheck({ run }: { run: Run }) {
  const kinds = useApi("script-kinds", () => api.scriptKinds());
  const config = useApi(`config:${run.config_id}`, () => api.configuration(run.config_id));
  const [code, setCode] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [name, setName] = useState("Новая проверка");
  const [includeExisting, setIncludeExisting] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [phase, setPhase] = useState<"edit" | "saving" | "running">("edit");
  const [checkRun, setCheckRun] = useState<CheckRun | null>(null);
  const alive = useRef(true);
  useEffect(() => () => void (alive.current = false), []);

  const checkKind = kinds.data?.find((k) => k.kind === "check");
  const text = code ?? checkKind?.template ?? "";

  async function submit() {
    setError(null);
    setPhase("saving");
    try {
      const script = await api.createScript({
        kind: "check",
        source: filename ? "file" : "workspace",
        name,
        code: text,
        ...(filename ? { filename } : {}),
      });
      const existing: ScriptRef[] = includeExisting ? config.data?.checks ?? [] : [];
      const acc = await api.createCheckRun(run.run_id, { checks: [...existing, { script_id: script.script_id }] });
      if (!acc.check_run_id) throw new Error("Backend не вернул check_run_id");
      setPhase("running");
      // Poll check-run until terminal, then switch to its (new) report_id explicitly.
      for (;;) {
        const cr = await api.checkRun(acc.check_run_id);
        if (!alive.current) return;
        setCheckRun(cr);
        if (cr.status === "COMPLETED") {
          navigate(`${href("runs", run.run_id, "checks")}?report=${encodeURIComponent(cr.report_id)}`);
          return;
        }
        if (cr.status === "FAILED") {
          setError(cr.error ? new ApiError(0, cr.error) : new Error("CheckRun завершился с ошибкой (FAILED)"));
          setPhase("edit");
          return;
        }
        await new Promise((r) => setTimeout(r, CHECK_POLL_MS));
      }
    } catch (e) {
      if (!alive.current) return;
      setError(e);
      setPhase("edit");
    }
  }

  return (
    <div>
      <h2>Новая проверка</h2>
      <ExecutionModeNote />
      <Async value={kinds} what="Загрузка контракта проверки">
        {() =>
          checkKind ? (
            <details>
              <summary>Контракт проверки</summary>
              <p>
                <code>{checkKind.entrypoint}</code>
              </p>
              <p>Колонки результата: {checkKind.output_columns.join(", ")}</p>
              <button type="button" onClick={() => setCode(checkKind.example)}>
                Вставить пример
              </button>{" "}
              <button type="button" onClick={() => setCode(checkKind.template)}>
                Вставить шаблон
              </button>
            </details>
          ) : (
            <p className="muted">Backend не описал kind=check.</p>
          )
        }
      </Async>
      <label>
        Название
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required />
      </label>
      <PythonEditor
        value={text}
        onChange={(c) => {
          setCode(c);
        }}
        onFile={(f) => {
          setFilename(f);
          setName(f.replace(/\.py$/, ""));
        }}
        label="Код проверки"
      />
      {filename ? (
        <p className="muted">
          Источник: файл <code>{filename}</code>{" "}
          <button type="button" onClick={() => setFilename(null)}>
            считать кодом из редактора
          </button>
        </p>
      ) : null}
      <label>
        <input type="checkbox" checked={includeExisting} onChange={(e) => setIncludeExisting(e.target.checked)} /> включить в отчёт исходные проверки конфигурации
        {config.data ? ` (${config.data.checks.length})` : ""}
      </label>
      {error ? <ErrorView error={error} /> : null}
      {phase === "running" ? (
        <p role="status">
          Проверки исполняются на сервере… CheckRun <code>{checkRun?.check_run_id}</code>: {checkRun?.status ?? "QUEUED"}
        </p>
      ) : null}
      <button type="button" className="primary" disabled={phase !== "edit" || !text.trim() || !name.trim()} onClick={submit}>
        {phase === "saving" ? "Сохранение…" : "Сохранить и запустить проверки"}
      </button>
    </div>
  );
}
