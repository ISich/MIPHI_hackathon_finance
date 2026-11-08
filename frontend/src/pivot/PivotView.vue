<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ApiError } from "../api/client";
import { api } from "../api/instance";
import type { PivotResponse, Run } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import { useApi } from "../composables/useApi";
import { href, navigate } from "../router";
import BaseFactsView from "./BaseFactsView.vue";
import PivotControls from "./PivotControls.vue";
import PivotTable from "./PivotTable.vue";
import { parsePivotQuery, pivotQuery, pivotRequest, type PivotState } from "./query";

const props = defineProps<{ run: Run; query: URLSearchParams; runName?: string }>();
const state = computed(() => parsePivotQuery(props.query));
const qs = computed(() => pivotQuery(state.value));
const reportCtx = computed(() => props.query.get("report"));
const offset = ref(0);
watch(() => `${props.run.run_id}:${qs.value}`, () => { offset.value = 0; }, { flush: "sync" });
const pivot = useApi(
  () => `pivot:${props.run.run_id}:${qs.value}:${offset.value}`,
  () =>
    api.pivot(props.run.run_id, pivotRequest(state.value, offset.value)),
);
const unavailable = computed(() => (pivot.error instanceof ApiError && pivot.error.isUnavailable ? pivot.error : null));
const go = (s: PivotState) =>
  navigate(`${href("runs", props.run.run_id, "pivot")}?${pivotQuery(s)}${reportCtx.value ? `&report=${encodeURIComponent(reportCtx.value)}` : ""}`);
/** Back-query for drill-down: layout + explicit report context. */
const backQuery = computed(() => (reportCtx.value ? `${qs.value}${qs.value ? "&" : ""}report=${encodeURIComponent(reportCtx.value)}` : qs.value));
const isEmpty = (d: PivotResponse) => d.total === 0;
const checksHref = computed(() => `${href("runs", props.run.run_id, "checks")}?report=${encodeURIComponent(reportCtx.value ?? "")}`);
</script>

<template>
  <div>
    <p v-if="reportCtx" class="state state-ok" data-testid="report-context">
      Открыто из отчёта <code>{{ reportCtx }}</code> — сводная запуска «{{ runName || 'Запуск' }}» (<code>{{ run.run_id }}</code>).
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
      <BaseFactsView :run="run" :report="reportCtx" />
    </template>
    <template v-else>
      <PivotControls :state="state" @change="go" />
      <AsyncView :value="pivot" what="Расчёт сводной на сервере" :is-empty="isEmpty" empty="Нет данных для выбранных фильтров.">
        <template #default="{ data }">
          <PivotTable v-if="data.run_id === run.run_id" :data="data" :rows="state.rows" :cols="state.cols" :run-id="run.run_id" :back-query="backQuery" />
          <div class="pager">
            <button :disabled="offset === 0" @click="offset = Math.max(0, offset - data.limit)">← Назад</button>
            <span>Группы {{ offset + 1 }}–{{ offset + data.items.length }} из {{ data.total }}</span>
            <button :disabled="offset + data.limit >= data.total" @click="offset += data.limit">Далее →</button>
          </div>
        </template>
      </AsyncView>
    </template>
  </div>
</template>
