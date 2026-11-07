import { api } from "../api/instance";
import { Async } from "../components/StateView";
import { RunStatusBadge } from "../components/Badges";
import { useApi, usePolling } from "../hooks/useApi";
import { href } from "../router";

export function RunsList() {
  const runs = useApi("runs", () => api.runs());
  const active = !!runs.data?.some((r) => r.status === "QUEUED" || r.status === "RUNNING");
  usePolling(active, 3000, async () => runs.reload(), []);
  return (
    <section>
      <div className="row-between">
        <h1>Запуски</h1>
        <a className="button primary" href={href("runs", "new")}>
          Новый запуск
        </a>
      </div>
      <Async value={runs} what="Загрузка запусков" isEmpty={(d) => d.length === 0} empty="Запусков пока нет.">
        {(list) => (
          <table className="table" aria-label="Список запусков">
            <thead>
              <tr>
                <th>Run</th>
                <th>Статус</th>
                <th>Этап</th>
                <th>Конфигурация</th>
                <th>Создан</th>
              </tr>
            </thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.run_id}>
                  <td>
                    <a href={href("runs", r.run_id)}>{r.run_id}</a>
                  </td>
                  <td>
                    <RunStatusBadge status={r.status} />
                  </td>
                  <td>{r.stage ?? "—"}</td>
                  <td>{r.config_id}</td>
                  <td>{r.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </section>
  );
}
