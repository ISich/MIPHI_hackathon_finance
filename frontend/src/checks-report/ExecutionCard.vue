<script setup lang="ts">
import { computed } from "vue";
import type { CheckExecution, CheckRow, ReportChecks } from "../api/types";
import ExecBadge from "../components/ExecBadge.vue";
import CheckRowsTable from "./CheckRowsTable.vue";

const props = defineProps<{ ex: CheckExecution; rows: CheckRow[] | null; doc: ReportChecks; runId: string; returnTo: string }>();
const ok = computed(() => props.ex.execution_status === "SUCCEEDED");
const diags = computed(() => props.doc.diagnostics.filter((d) => d.check === (props.ex.check_id ?? props.ex.slot) || d.check === props.ex.slot));
</script>

<template>
  <article :class="['card', { 'card-error': !ok }]" data-testid="check-execution" :data-exec-status="ex.execution_status">
    <header class="row-between">
      <h3>
        {{ ex.label ?? ex.check_id ?? ex.slot }} <span class="muted">({{ ex.check_id ?? "id неизвестен" }}, {{ ex.slot }})</span>
      </h3>
      <ExecBadge :status="ex.execution_status" />
    </header>
    <div class="muted">
      Параметры: <code>{{ JSON.stringify(ex.params ?? {}) }}</code>{{ ex.duration_seconds !== null ? ` · ${ex.duration_seconds} с` : "" }}
    </div>
    <div v-if="!ok" class="state state-error">
      Проверка не исполнилась — это не FAIL, бизнес-результата нет.
      <div v-for="(d, i) in diags" :key="i">
        <code>{{ String(d.error_type ?? "") }}</code> {{ String(d.message ?? "") }}
      </div>
    </div>
    <template v-else-if="rows !== null">
      <p v-if="rows.length === 0" class="muted">Исполнена успешно, 0 строк результата (это не PASS).</p>
      <CheckRowsTable v-else :rows="rows" :run-id="runId" :return-to="returnTo" :label="`Результаты ${ex.check_id ?? ex.slot}`" />
    </template>
  </article>
</template>
