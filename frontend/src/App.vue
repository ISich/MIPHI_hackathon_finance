<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, IS_MOCK } from "./api/instance";
import type { AccountUser } from "./api/types";
import LoginView from "./auth/LoginView.vue";
import MockBanner from "./components/MockBanner.vue";
import DashboardShell from "./components/DashboardShell.vue";
import ApplicationView from "./drilldown/ApplicationView.vue";
import FactApplications from "./drilldown/FactApplications.vue";
import GroupApplications from "./drilldown/GroupApplications.vue";
import NewScript from "./editor/NewScript.vue";
import ScriptsList from "./editor/ScriptsList.vue";
import ScriptView from "./editor/ScriptView.vue";
import { href, navigate, useRoute } from "./router";
import NewRun from "./run-config/NewRun.vue";
import RunPage from "./run-monitor/RunPage.vue";
import RunsList from "./run-monitor/RunsList.vue";

const route = useRoute();
const user = ref<AccountUser | null>(null);
const checking = ref(true);
const sessionError = ref("");
const signingOut = ref(false);
let generation = 0;

async function restoreSession() {
  const current = ++generation;
  sessionError.value = "";
  try {
    const session = await api.currentSession();
    if (current === generation) user.value = session.authenticated ? session.user : null;
  } catch (e) {
    if (current === generation) {
      user.value = null;
      sessionError.value = e instanceof Error ? e.message : "Не удалось проверить вход.";
    }
  } finally {
    if (current === generation) checking.value = false;
  }
}

function signedIn(account: AccountUser) {
  generation++;
  user.value = account;
  sessionError.value = "";
}

async function signOut() {
  if (signingOut.value) return;
  generation++;
  signingOut.value = true;
  sessionError.value = "";
  try {
    await api.logout();
    user.value = null;
    navigate(href("runs"));
  } catch (e) {
    sessionError.value = e instanceof Error ? e.message : "Не удалось выйти. Повторите попытку.";
  } finally {
    signingOut.value = false;
  }
}

function onFocus() {
  if (!signingOut.value && !checking.value) void restoreSession();
}
onMounted(() => {
  try { document.documentElement.dataset.theme = localStorage.getItem("spr.theme") === "dark" ? "dark" : "light"; } catch {}
  void restoreSession();
  window.addEventListener("focus", onFocus);
});
onUnmounted(() => {
  generation++;
  window.removeEventListener("focus", onFocus);
});
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
  <MockBanner v-if="IS_MOCK && !user" />
  <main v-if="checking || signingOut" class="session-loading" role="status">{{ signingOut ? 'Выходим из системы…' : 'Проверяем вход…' }}</main>
  <main v-else-if="!user" class="auth-main">
    <div v-if="sessionError" class="state state-error" role="alert">
      {{ sessionError }}
      <button type="button" @click="checking = true; restoreSession()">Повторить</button>
    </div>
    <LoginView @signed-in="signedIn" />
  </main>
  <DashboardShell v-else :key="user.username" :user="user" @sign-out="signOut">
    <div v-if="sessionError" class="state state-error" role="alert">{{ sessionError }}</div>
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
