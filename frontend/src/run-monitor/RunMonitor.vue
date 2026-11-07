<script setup lang="ts">
import { computed } from "vue";
import { slotOfCodeRef } from "../api/client";
import { RUN_STAGES, type Run, type RunEvent } from "../api/types";
import ProgressBar from "../components/ProgressBar.vue";
import CodeSnapshotLink from "./CodeSnapshotLink.vue";

const props = defineProps<{ run: Run; events: RunEvent[] }>();
const stageIdx = computed(() => RUN_STAGES.indexOf(props.run.stage as (typeof RUN_STAGES)[number]));
const stageClass = (i: number) => (i < stageIdx.value || props.run.status === "COMPLETED" ? "done" : i === stageIdx.value ? "current" : "");
</script>

<template>
  <div>
    <dl class="kv">
      <dt>Статус</dt>
      <dd data-testid="run-status">{{ run.status }}</dd>
      <dt>Этап</dt>
      <dd data-testid="run-stage">{{ run.stage ?? "—" }}{{ run.substep ? ` / ${run.substep}` : "" }}</dd>
      <dt>Конфигурация</dt>
      <dd>{{ run.config_id }}</dd>
      <dt>Dataset revision</dt>
      <dd>{{ run.dataset_revision_id }}</dd>
      <dt>Initial report</dt>
      <dd>{{ run.initial_report_id }} ({{ run.report_status ?? "—" }}{{ run.checks_completeness ? `, ${run.checks_completeness}` : "" }})</dd>
    </dl>
    <ol class="stages" aria-label="Этапы">
      <li v-for="(s, i) in RUN_STAGES" :key="s" :class="stageClass(i)">{{ s }}</li>
    </ol>
    <ProgressBar v-if="run.status === 'RUNNING' || run.status === 'QUEUED'" :processed="run.processed" :total="run.total" />
    <div v-if="run.status === 'FAILED'" class="state state-error" role="alert">
      <strong>Run завершился с ошибкой (FAILED).</strong> Отчёт не публикуется.
      <div v-if="run.error">
        <code>{{ run.error.code }}</code>: {{ run.error.message }}
      </div>
    </div>
    <p v-if="run.status !== 'COMPLETED'" class="muted">Отчёт станет доступен после завершения Run.</p>
    <h2>Журнал</h2>
    <p v-if="events.length === 0" class="muted">Событий пока нет.</p>
    <table class="table" aria-label="Журнал событий">
      <tbody>
        <tr v-for="e in events" :key="e.seq" :class="`level-${String(e.level).toLowerCase()}`">
          <td>{{ e.seq }}</td>
          <td>{{ e.ts }}</td>
          <td>{{ e.stage ?? "" }}{{ e.substep ? ` / ${e.substep}` : "" }}</td>
          <td>{{ e.level }}</td>
          <td>{{ e.message }}</td>
          <td><CodeSnapshotLink v-if="slotOfCodeRef(e.code_ref)" :run-id="run.run_id" :slot="slotOfCodeRef(e.code_ref)!" /></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
