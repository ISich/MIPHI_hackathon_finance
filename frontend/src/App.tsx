import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { ApiError, api, type Dataset, type Run, type RunEvent, type ScriptKind, type ScriptKindInfo, type SlotRef } from './api';
import { mockApi } from './mockApi';

type View = 'configure' | 'workspace' | 'monitor';
type ProcedureKind = Exclude<ScriptKind, 'check'>;

const procedureKinds: ProcedureKind[] = ['normalize', 'compare', 'segments', 'aggregate'];
const useMock = import.meta.env.MODE === 'mock';
const client = useMock ? mockApi : api;

function describeError(error: unknown) {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return 'Неизвестная ошибка';
}

function shortId(value: string) {
  return value.length > 18 ? `${value.slice(0, 18)}…` : value;
}

export default function App() {
  const [view, setView] = useState<View>('configure');
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [kinds, setKinds] = useState<ScriptKindInfo[]>([]);
  const [selectedDataset, setSelectedDataset] = useState('');
  const [configName, setConfigName] = useState('Новый запуск');
  const [selectedKind, setSelectedKind] = useState<ScriptKind>('normalize');
  const [editorText, setEditorText] = useState('');
  const [savedScripts, setSavedScripts] = useState<Partial<Record<ProcedureKind, string>>>({});
  const [status, setStatus] = useState('Загружаем доступные наборы и контракты…');
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);

  const selectedKindInfo = useMemo(
    () => kinds.find((item) => item.kind === selectedKind),
    [kinds, selectedKind],
  );

  useEffect(() => {
    let active = true;
    Promise.all([client.listDatasets(), client.listScriptKinds()])
      .then(([nextDatasets, nextKinds]) => {
        if (!active) return;
        setDatasets(nextDatasets);
        setKinds(nextKinds);
        setSelectedDataset(nextDatasets[0]?.dataset_id ?? '');
        setEditorText(nextKinds.find((item) => item.kind === 'normalize')?.template ?? '');
        setStatus(nextDatasets.length ? 'Готово к настройке запуска.' : 'Нет доступных dataset.');
      })
      .catch((nextError) => {
        if (!active) return;
        setError(describeError(nextError));
        setStatus('Не удалось загрузить данные для конфигурации.');
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!run || run.status === 'COMPLETED' || run.status === 'FAILED') return;
    const timer = window.setInterval(() => {
      Promise.all([client.getRun(run.run_id), client.getEvents(run.run_id, events.at(-1)?.seq ?? 0)])
        .then(([nextRun, nextEvents]) => {
          setRun(nextRun);
          setEvents((current) => [...current, ...nextEvents.items.filter((item) => !current.some((event) => event.seq === item.seq))]);
        })
        .catch((nextError) => setError(describeError(nextError)));
    }, 900);
    return () => window.clearInterval(timer);
  }, [run, events]);

  function selectKind(kind: ScriptKind) {
    setSelectedKind(kind);
    setEditorText(kinds.find((item) => item.kind === kind)?.template ?? '');
    setView('workspace');
  }

  async function saveWorkspace() {
    setError(null);
    setStatus('Сохраняем Python-скрипт как новый workspace artifact…');
    try {
      const result = await client.saveScript({
        kind: selectedKind,
        name: `${selectedKind} draft`,
        code: editorText,
      });
      if (selectedKind !== 'check') {
        setSavedScripts((current) => ({ ...current, [selectedKind]: result.script_id }));
      }
      setStatus(`Сохранён ${selectedKind}: ${shortId(result.script_id)}. Следующий Run зафиксирует этот snapshot.`);
    } catch (nextError) {
      setError(describeError(nextError));
      setStatus('Скрипт не сохранён. В режиме builtin-only custom code ожидаемо запрещён.');
    }
  }

  async function createAndStart(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!selectedDataset) {
      setError('Выбери dataset до запуска.');
      return;
    }
    const slots: Partial<Record<ProcedureKind, SlotRef>> = {};
    procedureKinds.forEach((kind) => {
      slots[kind] = { script_id: savedScripts[kind] ?? null, params: null };
    });

    try {
      setStatus('Сохраняем конфигурацию…');
      const configuration = await client.createConfiguration({
        name: configName.trim() || 'Новый запуск',
        dataset_id: selectedDataset,
        slots,
      });
      setStatus('Run принят backend. Открываем мониторинг…');
      const acceptedRun = await client.startRun(configuration.config_id);
      setRun(acceptedRun);
      setEvents([]);
      setView('monitor');
    } catch (nextError) {
      setError(describeError(nextError));
      setStatus('Конфигурация или Run не созданы.');
    }
  }

  const progressKnown = run?.processed !== null && run?.total !== null && run?.total !== undefined && run.total > 0;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">D3 · frontend workspace</p>
          <h1>Анализ изменений СПР</h1>
        </div>
        <span className={useMock ? 'mode mock' : 'mode real'}>{useMock ? 'MOCK · только разработка' : 'API · реальный backend'}</span>
      </header>

      {useMock && <p className="mock-banner">Данные и Run синтетические. Этот режим не подтверждает расчёт на стенде.</p>}

      <nav className="tabs" aria-label="Рабочая область">
        <button className={view === 'configure' ? 'active' : ''} onClick={() => setView('configure')}>Конфигурация</button>
        <button className={view === 'workspace' ? 'active' : ''} onClick={() => setView('workspace')}>Python-редактор</button>
        <button className={view === 'monitor' ? 'active' : ''} onClick={() => setView('monitor')} disabled={!run}>Run monitor</button>
      </nav>

      <section className="notice" aria-live="polite">{status}</section>
      {error && <section className="error" role="alert"><strong>Ошибка:</strong> {error}</section>}

      {view === 'configure' && (
        <section className="panel">
          <div className="section-title"><div><p className="eyebrow">Шаг 1</p><h2>Конфигурация запуска</h2></div><span>Run сохраняет выбранные snapshots</span></div>
          <form onSubmit={createAndStart} className="form-grid">
            <label>
              Имя конфигурации
              <input value={configName} onChange={(event) => setConfigName(event.target.value)} maxLength={120} />
            </label>
            <label>
              Dataset
              <select value={selectedDataset} onChange={(event) => setSelectedDataset(event.target.value)}>
                {!datasets.length && <option value="">Нет доступных наборов</option>}
                {datasets.map((dataset) => <option key={dataset.dataset_id} value={dataset.dataset_id}>{dataset.name}</option>)}
              </select>
            </label>
            <fieldset className="slot-grid">
              <legend>Процедуры по слотам</legend>
              {procedureKinds.map((kind) => (
                <button className="slot-card" type="button" key={kind} onClick={() => selectKind(kind)}>
                  <strong>{kind}</strong>
                  <span>{savedScripts[kind] ? `workspace: ${shortId(savedScripts[kind]!)}` : 'builtin (по умолчанию)'}</span>
                  <small>Открыть редактор</small>
                </button>
              ))}
            </fieldset>
            <aside className="hint"><strong>Checks:</strong> пока backend использует все встроенные проверки. Выбор и новая check-процедура будут добавлены следующим D3-шагом.</aside>
            <div className="actions"><button className="primary" type="submit" disabled={!selectedDataset}>Сохранить и запустить</button><button type="button" onClick={() => setView('workspace')}>Открыть редактор</button></div>
          </form>
        </section>
      )}

      {view === 'workspace' && (
        <section className="panel">
          <div className="section-title"><div><p className="eyebrow">Шаг 2</p><h2>Python workspace</h2></div><span>Код экранирован как текст и создаёт новый artifact</span></div>
          <div className="workspace-layout">
            <aside className="kind-list" aria-label="Тип процедуры">
              {(kinds.length ? kinds : procedureKinds.map((kind) => ({ kind, entrypoint: '', template: '', example: '', sources: [], custom_execution_enabled: false }))).map((kind) => (
                <button key={kind.kind} className={selectedKind === kind.kind ? 'active' : ''} onClick={() => selectKind(kind.kind)}>{kind.kind}</button>
              ))}
            </aside>
            <div className="editor-area">
              <p className="entrypoint">{selectedKindInfo?.entrypoint || 'Контракт загружается…'}</p>
              <textarea aria-label="Python код" value={editorText} onChange={(event) => setEditorText(event.target.value)} spellCheck={false} />
              <div className="actions"><button className="primary" onClick={saveWorkspace} disabled={!editorText.trim()}>Применить как новый script</button><button onClick={() => setEditorText(selectedKindInfo?.template ?? '')}>Вернуть шаблон</button></div>
              {selectedKindInfo && !selectedKindInfo.custom_execution_enabled && <p className="hint">Этот backend в режиме builtin-only: сохранение custom script вернёт 403, что UI покажет как ожидаемое ограничение.</p>}
            </div>
          </div>
        </section>
      )}

      {view === 'monitor' && run && (
        <section className="panel">
          <div className="section-title"><div><p className="eyebrow">Шаг 3</p><h2>Run monitor</h2></div><span>{shortId(run.run_id)}</span></div>
          <div className="run-summary">
            <div><span>Статус</span><strong>{run.status}</strong></div>
            <div><span>Этап</span><strong>{run.stage ? `${run.stage}${run.substep ? ` / ${run.substep}` : ''}` : 'ожидание worker'}</strong></div>
            <div><span>Report</span><strong>{run.report_status ?? 'PENDING'}</strong></div>
          </div>
          {progressKnown ? <progress value={run.processed ?? 0} max={run.total ?? 1}>{run.processed}/{run.total}</progress> : <p className="unknown-progress">Прогресс пока не измеряется для этого этапа — процент не выдумывается.</p>}
          {run.error && <section className="error" role="alert">{run.error.code ?? 'RUN_ERROR'}: {run.error.message}</section>}
          <ol className="journal">{events.length ? events.map((item) => <li key={item.seq}><time>{new Date(item.ts).toLocaleTimeString()}</time><span className={`event-${item.level.toLowerCase()}`}>{item.level}</span><span>{item.message}</span></li>) : <li>Ждём журнал Run…</li>}</ol>
          {run.status === 'COMPLETED' && <p className="complete">Run завершён. Следующая итерация подключит summary и drill-down по published report.</p>}
        </section>
      )}
    </main>
  );
}
