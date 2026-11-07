import { useMemo, useRef, useState, type FormEvent } from "react";
import { newIdempotencyKey } from "../api/client";
import { api } from "../api/instance";
import { PROCEDURE_SLOTS, type ProcedureSlot, type Script } from "../api/types";
import { Async, ErrorView } from "../components/StateView";
import { useApi } from "../hooks/useApi";
import { href, navigate } from "../router";

/**
 * Configuration screen: dataset + one procedure per slot (built-in or a saved
 * workspace/.py script) + selected checks → POST configurations → POST runs.
 */
export function NewRun() {
  const datasets = useApi("datasets", () => api.datasets());
  const scripts = useApi("scripts", () => api.scripts());
  const configs = useApi("configurations", () => api.configurations());

  const [mode, setMode] = useState<"new" | "saved">("new");
  const [savedId, setSavedId] = useState("");
  const [name, setName] = useState("Конфигурация");
  const [datasetId, setDatasetId] = useState("");
  const [slots, setSlots] = useState<Partial<Record<ProcedureSlot, string>>>({});
  const [checks, setChecks] = useState<Set<string> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  // Retry safety: the same form state reuses the already created configuration and
  // the same Idempotency-Key, so a retried submit (e.g. after a network error)
  // replays the accepted Run instead of silently creating a duplicate.
  const attempt = useRef<{ form: string; configId?: string; key: string } | null>(null);

  const byKind = useMemo(() => {
    const m: Record<string, Script[]> = {};
    for (const s of scripts.data ?? []) (m[s.kind] ??= []).push(s);
    return m;
  }, [scripts.data]);
  const checkScripts = byKind["check"] ?? [];
  const selectedChecks = checks ?? new Set(checkScripts.filter((s) => s.shared).map((s) => s.script_id));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const cfgReq = {
        name,
        dataset_id: datasetId,
        slots: Object.fromEntries(
          Object.entries(slots)
            .filter(([, v]) => v)
            .map(([k, v]) => [k, { script_id: v! }]),
        ),
        checks: [...selectedChecks].sort().map((script_id) => ({ script_id })),
      };
      const form = JSON.stringify(mode === "new" ? cfgReq : { savedId });
      if (attempt.current?.form !== form) attempt.current = { form, key: newIdempotencyKey() };
      const a = attempt.current;
      if (mode === "saved") a.configId = savedId;
      if (!a.configId) a.configId = (await api.createConfiguration(cfgReq)).config_id;
      const run = await api.createRun({ configuration_id: a.configId }, a.key);
      navigate(href("runs", run.run_id));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h1>Новый запуск</h1>
      <form onSubmit={submit} className="form" aria-label="Новый запуск">
        <fieldset>
          <legend>Источник конфигурации</legend>
          <label>
            <input type="radio" name="mode" checked={mode === "new"} onChange={() => setMode("new")} /> Новая конфигурация
          </label>
          <label>
            <input type="radio" name="mode" checked={mode === "saved"} onChange={() => setMode("saved")} /> Сохранённая
          </label>
        </fieldset>

        {mode === "saved" ? (
          <Async value={configs} isEmpty={(d) => d.length === 0} empty="Сохранённых конфигураций нет.">
            {(list) => (
              <label>
                Конфигурация
                <select value={savedId} onChange={(e) => setSavedId(e.target.value)} required>
                  <option value="">— выберите —</option>
                  {list.map((c) => (
                    <option key={c.config_id} value={c.config_id}>
                      {c.name} ({c.config_id})
                    </option>
                  ))}
                </select>
              </label>
            )}
          </Async>
        ) : (
          <>
            <label>
              Название
              <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
            </label>
            <Async value={datasets} what="Загрузка наборов" isEmpty={(d) => d.length === 0} empty="Нет доступных наборов данных.">
              {(list) => (
                <label>
                  Набор данных
                  <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)} required>
                    <option value="">— выберите —</option>
                    {list.map((d) => {
                      const rev = d.revisions[d.revisions.length - 1];
                      return (
                        <option key={d.dataset_id} value={d.dataset_id}>
                          {d.name}
                          {rev ? ` — пар: ${rev.pairs}` : ""}
                        </option>
                      );
                    })}
                  </select>
                </label>
              )}
            </Async>
            <Async value={scripts} what="Загрузка процедур">
              {() => (
                <>
                  <fieldset>
                    <legend>Процедуры по слотам</legend>
                    {PROCEDURE_SLOTS.map((slot) => (
                      <label key={slot}>
                        {slot}
                        <select
                          value={slots[slot] ?? ""}
                          onChange={(e) => setSlots({ ...slots, [slot]: e.target.value })}
                          aria-label={`Процедура ${slot}`}
                        >
                          <option value="">встроенная (по умолчанию)</option>
                          {(byKind[slot] ?? []).map((s) => (
                            <option key={s.script_id} value={s.script_id}>
                              {s.name} [{s.source}
                              {s.source !== "builtin" ? `, rev ${s.revision}` : ""}]
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                    <p className="muted">
                      Свою процедуру создайте в <a href={href("scripts", "new")}>рабочей области</a> — она появится в списке слота.
                    </p>
                  </fieldset>
                  <fieldset>
                    <legend>Проверки</legend>
                    {checkScripts.length === 0 ? <p className="muted">Проверок нет.</p> : null}
                    {checkScripts.map((s) => (
                      <label key={s.script_id} className="check-option">
                        <input
                          type="checkbox"
                          checked={selectedChecks.has(s.script_id)}
                          onChange={(e) => {
                            const next = new Set(selectedChecks);
                            if (e.target.checked) next.add(s.script_id);
                            else next.delete(s.script_id);
                            setChecks(next);
                          }}
                        />
                        {s.name} <span className="muted">[{s.source}]</span>
                      </label>
                    ))}
                  </fieldset>
                </>
              )}
            </Async>
          </>
        )}

        {error ? <ErrorView error={error} /> : null}
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Запуск…" : "Сохранить конфигурацию и запустить"}
        </button>
      </form>
    </section>
  );
}
