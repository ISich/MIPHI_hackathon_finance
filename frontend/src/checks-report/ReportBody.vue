<script setup lang="ts">
import { computed } from "vue";
import { rowsByExecution } from "../api/client";
import type { ReportChecks } from "../api/types";
import EmptyView from "../components/EmptyView.vue";
import CheckRowsTable from "./CheckRowsTable.vue";
import ExecutionCard from "./ExecutionCard.vue";

const props = defineProps<{ doc: ReportChecks; runId: string }>();
const groups = computed(() => rowsByExecution(props.doc));
const failedExec = computed(() => props.doc.executions.filter((e) => e.execution_status !== "SUCCEEDED").length);
const failRows = computed(() => props.doc.checks.filter((r) => r.RESULT === "FAIL").length);
const passRows = computed(() => props.doc.checks.filter((r) => r.RESULT === "PASS").length);
</script>

<template>
  <div>
    <p class="check-summary" data-testid="check-summary">
      Отчёт <code>{{ doc.report_id }}</code>, полнота: <strong>{{ doc.completeness }}</strong>. Проверок: {{ doc.executions.length }}; строк FAIL:
      {{ failRows }}, PASS: {{ passRows
      }}<template v-if="failedExec">; <strong class="err">ошибок исполнения: {{ failedExec }}</strong> (отчёт по проверкам неполный)</template>
    </p>
    <EmptyView v-if="doc.completeness === 'NO_CHECKS_SELECTED'">Проверки не выбирались (технический Run).</EmptyView>
    <template v-if="groups">
      <ExecutionCard v-for="g in groups" :key="g.ex.execution_id" :ex="g.ex" :rows="g.rows" :doc="doc" :run-id="runId" />
    </template>
    <template v-else>
      <div class="state state-notready">Число строк не сходится с rows_count исполнений — строки показаны без привязки к проверке.</div>
      <ExecutionCard v-for="ex in doc.executions" :key="ex.execution_id" :ex="ex" :rows="null" :doc="doc" :run-id="runId" />
      <CheckRowsTable :rows="doc.checks" :run-id="runId" label="Все строки отчёта" />
    </template>
  </div>
</template>
