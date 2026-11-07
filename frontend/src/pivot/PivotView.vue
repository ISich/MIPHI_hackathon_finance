<script setup lang="ts">
import { computed } from "vue";
import { ApiError } from "../api/client";
import { api } from "../api/instance";
import type { PivotResponse, Run } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import { useApi } from "../composables/useApi";
import { href, navigate } from "../router";
import BaseFactsView from "./BaseFactsView.vue";
import PivotControls from "./PivotControls.vue";
import PivotTable from "./PivotTable.vue";
import { parsePivotQuery, pivotQuery, type PivotState } from "./query";

const props = defineProps<{ run: Run; query: URLSearchParams }>();
const state = computed(() => parsePivotQuery(props.query));
const qs = computed(() => pivotQuery(state.value));
const reportCtx = computed(() => props.query.get("report"));
const pivot = useApi(
  () => `pivot:${props.run.run_id}:${qs.value}`,
  () =>
    api.pivot(props.run.run_id, {
      rows: state.value.rows,
      cols: state.value.cols,
      filters: state.value.filters,
      report_id: reportCtx.value ?? props.run.initial_report_id,
    }),
);
const unavailable = computed(() => (pivot.error instanceof ApiError && pivot.error.isUnavailable ? pivot.error : null));
const go = (s: PivotState) =>
  navigate(`${href("runs", props.run.run_id, "pivot")}?${pivotQuery(s)}${reportCtx.value ? `&report=${encodeURIComponent(reportCtx.value)}` : ""}`);
const isEmpty = (d: PivotResponse) => d.cells.length === 0 && d.grand_total.count === 0;
const checksHref = computed(() => `${href("runs", props.run.run_id, "checks")}?report=${encodeURIComponent(reportCtx.value ?? "")}`);
</script>

<template>
  <div>
    <p v-if="reportCtx" class="state state-ok" data-testid="report-context">
      Открыто из отчёта <code>{{ reportCtx }}</code> — сводная Run <code>{{ run.run_id }}</code>.
      <a :href="checksHref">Проверки этого отчёта</a>
    </p>
    <template v-if="unavailable">
      <div class="state state-disabled" role="note" data-testid="pivot-unavailable">
        <strong>Изменяемая сводная (server rollup) пока недоступна в backend:</strong> <code>{{ unavailable.code }}</code> — {{ unavailable.message }}
        <div>
          Ниже — базовые факты D4 (фиксированная детализация) с drill-down. Раскладку строк/колонок UI не пересчитывает сам: distinct-итоги должен
          считать сервер.
        </div>
      </div>
      <BaseFactsView :run="run" />
    </template>
    <template v-else>
      <PivotControls :state="state" @change="go" />
      <AsyncView :value="pivot" what="Расчёт сводной на сервере" :is-empty="isEmpty" empty="Нет данных для выбранных фильтров.">
        <template #default="{ data }">
          <PivotTable v-if="data.run_id === run.run_id" :data="data" :run-id="run.run_id" :back-query="qs" />
        </template>
      </AsyncView>
    </template>
  </div>
</template>
