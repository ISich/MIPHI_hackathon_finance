<script setup lang="ts">
import { computed, ref, shallowRef, watch } from "vue";
import { api } from "../api/instance";
import type { Run, RunEvent } from "../api/types";
import ChecksView from "../checks-report/ChecksView.vue";
import ErrorView from "../components/ErrorView.vue";
import LoadingView from "../components/LoadingView.vue";
import RunStatusBadge from "../components/RunStatusBadge.vue";
import { usePolling } from "../composables/useApi";
import { timing } from "../config";
import NewCheck from "../editor/NewCheck.vue";
import PivotView from "../pivot/PivotView.vue";
import SummaryView from "../report-summary/SummaryView.vue";
import { href } from "../router";
import RunMonitor from "./RunMonitor.vue";

const TABS = [
  ["monitor", "Мониторинг"],
  ["summary", "Сводка"],
  ["pivot", "Сводная (pivot)"],
  ["checks", "Проверки"],
  ["new-check", "Новая проверка"],
] as const;
type Tab = (typeof TABS)[number][0];

/** Run monitor + report tabs. Polls status and events with ?after=seq while the Run is active. */
const props = defineProps<{ runId: string; tab?: string; query: URLSearchParams }>();

const run = shallowRef<Run | undefined>();
const error = ref<unknown>(null);
const events = shallowRef<RunEvent[]>([]);
// Default tab: summary only if the Run was already finished when opened; a Run
// watched live stays on the monitor when it completes.
const openedCompleted = ref<boolean | null>(null);
let lastSeq = 0;

watch(
  () => props.runId,
  () => {
    run.value = undefined;
    error.value = null;
    events.value = [];
    openedCompleted.value = null;
    lastSeq = 0;
  },
);

const active = computed(() => !run.value || run.value.status === "QUEUED" || run.value.status === "RUNNING");
usePolling(
  () => active.value && !(error.value && !run.value),
  () => timing.runPollMs,
  async () => {
    const id = props.runId;
    try {
      // Status first, then events: once a terminal status is seen, the events
      // fetched afterwards already contain the final ones (polling stops then).
      const r = await api.run(id);
      const ev = await api.events(id, lastSeq);
      if (props.runId !== id) return; // stale: user switched Run
      run.value = r;
      if (openedCompleted.value === null) openedCompleted.value = r.status === "COMPLETED";
      error.value = null;
      if (ev.items.length) {
        lastSeq = Math.max(ev.next_after, ...ev.items.map((e) => e.seq));
        const seen = new Set(events.value.map((e) => e.seq));
        events.value = [...events.value, ...ev.items.filter((e) => !seen.has(e.seq))];
      }
    } catch (e) {
      if (props.runId === id) error.value = e;
    }
  },
  () => props.runId,
);

const completed = computed(() => run.value?.status === "COMPLETED");
const selected = computed<Tab>(
  () => TABS.find(([t]) => t === props.tab)?.[0] ?? (completed.value && openedCompleted.value ? "summary" : "monitor"),
);
</script>

<template>
  <section>
    <p><a :href="href('runs')">← Запуски</a></p>
    <h1>
      Run <code>{{ runId }}</code>{{ " " }}<RunStatusBadge v-if="run" :status="run.status" />
    </h1>
    <ErrorView v-if="error && !run" :error="error" />
    <div v-if="error && run" class="muted">Ошибка обновления статуса, повторяю…</div>
    <LoadingView v-if="!run && !error" what="Загрузка статуса" />
    <template v-if="run">
      <nav class="tabs" aria-label="Разделы запуска">
        <template v-for="[t, label] in TABS" :key="t">
          <span v-if="t !== 'monitor' && !completed" class="tab disabled" title="Отчёт доступен после завершения Run" aria-disabled="true">{{ label }}</span>
          <a v-else :class="['tab', { active: selected === t }]" :href="href('runs', runId, t)" :aria-current="selected === t ? 'page' : undefined">{{ label }}</a>
        </template>
      </nav>
      <RunMonitor v-if="selected === 'monitor' || !completed" :run="run" :events="events" />
      <SummaryView v-else-if="selected === 'summary'" :run="run" />
      <PivotView v-else-if="selected === 'pivot'" :run="run" :query="query" />
      <ChecksView v-else-if="selected === 'checks'" :run="run" :report-id="query.get('report')" />
      <NewCheck v-else :run="run" />
    </template>
  </section>
</template>
