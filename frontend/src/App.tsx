import { IS_MOCK } from "./api/instance";
import { MockBanner } from "./components/MockBanner";
import { useRoute, href } from "./router";
import { RunsList } from "./screens/RunsList";
import { NewRun } from "./screens/NewRun";
import { RunPage } from "./screens/RunPage";
import { ApplicationView, FactApplications, GroupApplications } from "./screens/Drilldown";
import { NewScript, ScriptView, ScriptsList } from "./screens/Workspace";

export function App() {
  const route = useRoute();
  const [section, id, sub, subId] = route.parts;
  let body;
  if (section === "runs" && id === "new") body = <NewRun />;
  else if (section === "runs" && id && sub === "groups" && subId)
    body = <GroupApplications key={subId} runId={id} group={subId} back={route.query.get("back") ?? ""} />;
  else if (section === "runs" && id && sub === "fact-apps")
    body = <FactApplications runId={id} group={route.query.get("g") ?? ""} cnt={route.query.get("cnt") ? Number(route.query.get("cnt")) : null} />;
  else if (section === "runs" && id && sub === "apps" && subId)
    body = <ApplicationView runId={id} appId={subId} group={route.query.get("group")} back={route.query.get("back") ?? ""} />;
  else if (section === "runs" && id) body = <RunPage runId={id} tab={sub} query={route.query} />;
  else if (section === "scripts" && id === "new") body = <NewScript fromId={route.query.get("from")} />;
  else if (section === "scripts" && id) body = <ScriptView scriptId={id} />;
  else if (section === "scripts") body = <ScriptsList />;
  else body = <RunsList />;

  return (
    <>
      {IS_MOCK ? <MockBanner /> : null}
      <header className="topbar">
        <a href={href("runs")} className="brand">
          Анализ изменений СПР
        </a>
        <nav aria-label="Основная навигация">
          <a href={href("runs")}>Запуски</a>
          <a href={href("runs", "new")}>Новый запуск</a>
          <a href={href("scripts")}>Рабочая область</a>
        </nav>
      </header>
      <main>{body}</main>
    </>
  );
}
