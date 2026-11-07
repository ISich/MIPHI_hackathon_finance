import { useEffect, useRef, useState } from "react";
import { ApiError, newIdempotencyKey } from "../api/client";
import { api } from "../api/instance";
import type { CheckRun, Run, Script, ScriptRef } from "../api/types";
import { PythonEditor } from "../components/PythonEditor";
import { Async, ErrorView } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href, navigate } from "../router";
import { ExecutionModeNote } from "../components/ExecutionModeNote";
import { saveScript } from "../api/actions";

export const CHECK_POLL_MS = 1500;

/**
 * "New check" scenario: editor or .py upload → saved snapshot → POST
 * /api/runs/{id}/check-runs with the Run's check set plus the new one → poll
 * the check-run → open the returned report_id explicitly.
 */
export function NewCheck({ run }: { run: Run }) {
  const kinds = useApi("script-kinds", () => api.scriptKinds());
  const config = useApi(`config:${run.config_id}`, () => api.configuration(run.config_id));
  const [code, setCode] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("Новая проверка");
  const [includeExisting, setIncludeExisting] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [phase, setPhase] = useState<"edit" | "saving" | "running">("edit");
  const [checkRun, setCheckRun] = useState<CheckRun | null>(null);
  const [saved, setSaved] = useState<{ key: string; script: Script } | null>(null);
  const crKey = useRef<{ scriptId: string; checks: string; key: string } | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const checkKind = kinds.data?.find((k) => k.kind === "check");
  const text = code ?? checkKind?.template ?? "";

  async function submit() {
    setError(null);
    setPhase("saving");
    try {
      // Re-use the saved snapshot if nothing changed since the last (failed) attempt.
      const saveKey = JSON.stringify([name, text, file?.name ?? null]);
      let script = saved?.key === saveKey ? saved.script : null;
      if (!script) {
        script = await saveScript("check", name, text, file);
        setSaved({ key: saveKey, script });
      }
      const existing: ScriptRef[] = includeExisting ? (config.data?.checks ?? []).filter((c) => c.script_id !== script!.script_id) : [];
      const checks = [...existing.map((c) => ({ script_id: c.script_id, params: c.params ?? null })), { script_id: script.script_id }];
      const checksKey = JSON.stringify(checks);
      if (crKey.current?.scriptId !== script.script_id || crKey.current.checks !== checksKey)
        crKey.current = { scriptId: script.script_id, checks: checksKey, key: newIdempotencyKey() };
      let cr = await api.createCheckRun(run.run_id, { checks }, crKey.current.key);
      setPhase("running");
      for (;;) {
        if (!alive.current) return;
        setCheckRun(cr);
        if (cr.status === "COMPLETED") {
          navigate(`${href("runs", run.run_id, "checks")}?report=${encodeURIComponent(cr.report_id)}`);
          return;
        }
        if (cr.status === "FAILED") {
          setError(cr.error ? new ApiError(0, { code: cr.error.code, message: cr.error.message ?? cr.error.code }) : new Error("CheckRun завершился с ошибкой (FAILED)"));
          setPhase("edit");
          return;
        }
        await new Promise((r) => setTimeout(r, CHECK_POLL_MS));
        cr = await api.checkRun(cr.check_run_id);
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
              <button type="button" onClick={() => (setCode(checkKind.example), setFile(null))}>
                Вставить пример
              </button>{" "}
              <button type="button" onClick={() => (setCode(checkKind.template), setFile(null))}>
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
          setFile(null); // edited text is a workspace script, not the uploaded file
        }}
        onFile={(f) => {
          setFile(f);
          setName(f.name.replace(/\.py$/, ""));
        }}
        label="Код проверки"
      />
      <p className="muted" data-testid="script-source">
        Источник: {file ? <>файл <code>{file.name}</code> (без изменений)</> : "редактор (workspace)"}
      </p>
      <label>
        <input type="checkbox" checked={includeExisting} onChange={(e) => setIncludeExisting(e.target.checked)} /> включить в новый отчёт исходные проверки
        конфигурации{config.data ? ` (${config.data.checks.length})` : ""}
      </label>
      {error ? <ErrorView error={error} /> : null}
      {saved && error ? (
        <p className="muted">
          Скрипт уже сохранён: <a href={href("scripts", saved.script.script_id)}>{saved.script.name}</a> (rev {saved.script.revision}).
        </p>
      ) : null}
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
