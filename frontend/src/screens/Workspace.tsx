import { useState } from "react";
import { api } from "../api/instance";
import type { Script, ScriptKindName } from "../api/types";
import { PythonEditor } from "../components/PythonEditor";
import { Async, ErrorView } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href } from "../router";
import { saveScript } from "../api/actions";
import { ExecutionModeNote } from "../components/ExecutionModeNote";

export function ScriptsList() {
  const scripts = useApi("scripts", () => api.scripts());
  return (
    <section>
      <div className="row-between">
        <h1>Рабочая область: скрипты</h1>
        <a className="button primary" href={href("scripts", "new")}>
          Новый скрипт
        </a>
      </div>
      <Async value={scripts} isEmpty={(d) => d.length === 0} empty="Скриптов нет.">
        {(list) => (
          <table className="table" aria-label="Скрипты">
            <thead>
              <tr>
                <th>Название</th>
                <th>Тип</th>
                <th>Источник</th>
                <th>Ревизия</th>
                <th>sha256</th>
              </tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.script_id}>
                  <td>
                    <a href={href("scripts", s.script_id)}>{s.name}</a>
                  </td>
                  <td>{s.kind}</td>
                  <td>{s.source}</td>
                  <td>{s.revision}</td>
                  <td>
                    <code>{s.code_sha256.slice(0, 12)}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </section>
  );
}

export function ScriptView({ scriptId }: { scriptId: string }) {
  const s = useApi(`script:${scriptId}`, () => api.script(scriptId));
  return (
    <section>
      <p>
        <a href={href("scripts")}>← Скрипты</a>
      </p>
      <Async value={s}>
        {(d) => (
          <div>
            <h1>{d.name}</h1>
            <p className="muted">
              {d.kind} · {d.source} · rev {d.revision} · sha256 {d.code_sha256}
            </p>
            <pre className="code-view">{d.code ?? "(код недоступен)"}</pre>
            <a className="button" href={`${href("scripts", "new")}?from=${encodeURIComponent(d.script_id)}`}>
              Создать изменённую копию
            </a>
          </div>
        )}
      </Async>
    </section>
  );
}

export function NewScript({ fromId }: { fromId: string | null }) {
  const kinds = useApi("script-kinds", () => api.scriptKinds());
  const from = useApi(fromId ? `script:${fromId}` : null, () => api.script(fromId!));
  const [kind, setKind] = useState<ScriptKindName | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<Script | null>(null);
  const [busy, setBusy] = useState(false);

  const effKind: ScriptKindName = kind ?? from.data?.kind ?? "check";
  const spec = kinds.data?.find((k) => k.kind === effKind);
  const text = code ?? from.data?.code ?? spec?.template ?? "";
  const effName = name || (from.data ? `${from.data.name} (копия)` : "");

  async function save() {
    setBusy(true);
    setError(null);
    try {
      setSaved(await saveScript(effKind, effName, text, file));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <p>
        <a href={href("scripts")}>← Скрипты</a>
      </p>
      <h1>Новый скрипт</h1>
      <ExecutionModeNote />
      <Async value={kinds} what="Загрузка контрактов">
        {(list) => (
          <div className="form">
            <label>
              Тип (слот)
              <select
                value={effKind}
                onChange={(e) => {
                  setKind(e.target.value as ScriptKindName);
                  setCode(null);
                  setFile(null);
                }}
              >
                {list.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {k.kind}
                  </option>
                ))}
              </select>
            </label>
            {spec ? (
              <details open>
                <summary>Контракт {spec.kind}</summary>
                <p>
                  <code>{spec.entrypoint}</code>
                </p>
                {spec.output_columns.length ? <p>Выходные колонки: {spec.output_columns.join(", ")}</p> : null}
                <button type="button" onClick={() => (setCode(spec.example), setFile(null))}>
                  Вставить пример
                </button>{" "}
                <button type="button" onClick={() => (setCode(spec.template), setFile(null))}>
                  Вставить шаблон
                </button>
              </details>
            ) : null}
            <label>
              Название
              <input value={effName} onChange={(e) => setName(e.target.value)} required maxLength={120} />
            </label>
            <PythonEditor
              value={text}
              onChange={(c) => {
                setCode(c);
                setFile(null);
              }}
              onFile={(f) => {
                setFile(f);
                if (!name) setName(f.name.replace(/\.py$/, ""));
              }}
            />
            <p className="muted" data-testid="script-source">
              Источник: {file ? <>файл <code>{file.name}</code> (без изменений)</> : "редактор (workspace)"}
            </p>
            {error ? <ErrorView error={error} /> : null}
            {saved ? (
              <div className="state state-ok" role="status">
                Сохранено: <a href={href("scripts", saved.script_id)}>{saved.name}</a> (rev {saved.revision}, sha256 {saved.code_sha256.slice(0, 12)}).{" "}
                {saved.kind === "check" ? "Запустите её на завершённом Run во вкладке «Новая проверка» или выберите в новой конфигурации." : "Выберите её в слоте новой конфигурации."}{" "}
                <a href={href("runs", "new")}>Новый запуск →</a>
              </div>
            ) : null}
            <button type="button" className="primary" onClick={save} disabled={busy || !text.trim() || !effName.trim()}>
              {busy ? "Сохранение…" : "Сохранить snapshot"}
            </button>
          </div>
        )}
      </Async>
    </section>
  );
}
