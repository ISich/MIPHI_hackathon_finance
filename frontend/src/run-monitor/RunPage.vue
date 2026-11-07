<script setup lang="ts">
import { computed, ref, shallowRef, watch } from "vue";
import { api } from "../api/instance";
import type { Run, RunEvent, Report } from "../api/types";
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

/** Run monitor + report tabs. Terminal Runs may still receive CheckRun events. */
const props = defineProps<{ runId: string; tab?: string; query: URLSearchParams }>();

const run = shallowRef<Run | undefined>();
const error = ref<unknown>(null);
const events = shallowRef<RunEvent[]>([]);
const reports = shallowRef<Report[]>([]);
// Default tab: summary only if the Run was already finished when opened; a Run
// watched live stays on the monitor when it completes.
const openedCompleted = ref<boolean | null>(null);
let lastSeq = 0;
/** Safety cap; with the backend's 500-event pages this is 500k events per tick. */
const MAX_EVENT_PAGES_PER_TICK = 1000;

watch(
  () => props.runId,
  () => {
    run.value = undefined;
    error.value = null;
    events.value = [];
    reports.value = [];
    openedCompleted.value = null;
    lastSeq = 0;
  },
);

usePolling(
  () => !(error.value && !run.value),
  () => run.value?.status === "COMPLETED" ? timing.listPollMs : timing.runPollMs,
  async () => {
    const id = props.runId;
    try {
      // Status first, then the whole event backlog: once a terminal status is
      // seen, the events drained afterwards contain the final ones, and polling
      // continues for check-only jobs after the data Run completes.
      const r = await api.run(id);
      if (props.runId !== id) return; // stale: user switched Run
      if (r.status === "COMPLETED") {
        const list = await api.reports(id);
        if (props.runId !== id) return;
        reports.value = list.items;
      }
      const fresh: RunEvent[] = [];
      let after = lastSeq;
      for (let page = 0; page < MAX_EVENT_PAGES_PER_TICK; page++) {
        const ev = await api.events(id, after);
        if (props.runId !== id) return;
        if (!ev.items.length) {
          break;
        }
        fresh.push(...ev.items);
        const next = Math.max(ev.next_after, ...ev.items.map((e) => e.seq));
        if (next <= after) {
          // Backend did not advance: avoid a tight loop.
          break;
        }
        after = next;
      }
      run.value = r;
      if (openedCompleted.value === null) openedCompleted.value = r.status === "COMPLETED";
      error.value = null;
      if (fresh.length) {
        lastSeq = after;
        const seen = new Set(events.value.map((e) => e.seq));
        events.value = [...events.value, ...fresh.filter((e) => !seen.has(e.seq))];
      }
    } catch (e) {
      if (props.runId === id) error.value = e;
    }
  },
  () => props.runId,
);

/** Explicitly chosen report travels with tab navigation (otherwise checks would fall back to the initial report). */
const reportSuffix = computed(() => (props.query.get("report") ? `?report=${encodeURIComponent(props.query.get("report")!)}` : ""));
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
          <a v-else :class="['tab', { active: selected === t }]" :href="href('runs', runId, t) + reportSuffix" :aria-current="selected === t ? 'page' : undefined">{{ label }}</a>
        </template>
      </nav>
      <RunMonitor v-if="selected === 'monitor' || !completed" :run="run" :events="events" />
      <SummaryView v-else-if="selected === 'summary'" :run="run" />
      <PivotView v-else-if="selected === 'pivot'" :run="run" :query="query" />
      <ChecksView v-else-if="selected === 'checks'" :run="run" :report-id="query.get('report')" />
      <NewCheck v-else :run="run" />
      <ul v-if="selected === 'monitor' && reports.length" aria-label="Отчёты запуска">
        <li v-for="report in reports" :key="report.report_id">
          <a :href="`${href('runs', runId, 'checks')}?report=${encodeURIComponent(report.report_id)}`">{{ report.report_id }} — {{ report.status }}</a>
        </li>
      </ul>
    </template>
  </section>
</template>
