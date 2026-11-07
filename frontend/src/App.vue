<script setup lang="ts">
import { computed } from "vue";
import DashboardShell from "./components/DashboardShell.vue";
import ApplicationView from "./drilldown/ApplicationView.vue";
import FactApplications from "./drilldown/FactApplications.vue";
import GroupApplications from "./drilldown/GroupApplications.vue";
import NewScript from "./editor/NewScript.vue";
import ScriptsList from "./editor/ScriptsList.vue";
import ScriptView from "./editor/ScriptView.vue";
import { useRoute } from "./router";
import NewRun from "./run-config/NewRun.vue";
import RunPage from "./run-monitor/RunPage.vue";
import RunsList from "./run-monitor/RunsList.vue";

const route = useRoute();
const view = computed(() => {
  const [section, id, sub, subId] = route.value.parts;
  const q = route.value.query;
  if (section === "overview") return { name: "overview" as const };
  if (section === "runs" && id === "new") return { name: "new-run" as const };
  if (section === "runs" && id && sub === "groups" && subId) return { name: "group" as const, runId: id, group: subId, back: q.get("back") ?? "" };
  if (section === "runs" && id && sub === "fact-apps")
    return { name: "fact-apps" as const, runId: id, group: q.get("g") ?? "", cnt: q.get("cnt") ? Number(q.get("cnt")) : null, report: q.get("report") };
  if (section === "runs" && id && sub === "apps" && subId)
    return { name: "app" as const, runId: id, appId: subId, group: q.get("group"), back: q.get("back") ?? "" };
  if (section === "runs" && id) return { name: "run" as const, runId: id, tab: sub, query: q };
  if (section === "scripts" && id === "new") return { name: "new-script" as const, fromId: q.get("from") };
  if (section === "scripts" && id) return { name: "script" as const, scriptId: id };
  if (section === "scripts") return { name: "scripts" as const };
  return { name: "runs" as const };
});
</script>

<template>
  <DashboardShell>
    <NewRun v-if="view.name === 'new-run'" />
    <GroupApplications v-else-if="view.name === 'group'" :key="view.group" :run-id="view.runId" :group="view.group" :back="view.back" />
    <FactApplications v-else-if="view.name === 'fact-apps'" :run-id="view.runId" :group="view.group" :cnt="view.cnt" :report="view.report" />
    <ApplicationView v-else-if="view.name === 'app'" :run-id="view.runId" :app-id="view.appId" :group="view.group" :back="view.back" />
    <RunPage v-else-if="view.name === 'run'" :run-id="view.runId" :tab="view.tab" :query="view.query" />
    <NewScript v-else-if="view.name === 'new-script'" :from-id="view.fromId" />
    <ScriptView v-else-if="view.name === 'script'" :script-id="view.scriptId" />
    <ScriptsList v-else-if="view.name === 'scripts'" />
    <RunsList v-else :key="view.name" :overview="view.name === 'overview'" />
  </DashboardShell>
</template>
