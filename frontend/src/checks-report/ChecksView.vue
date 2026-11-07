<script setup lang="ts">
import { computed } from "vue";
import { api } from "../api/instance";
import type { Run } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import EmptyView from "../components/EmptyView.vue";
import { useApi } from "../composables/useApi";
import { href, navigate } from "../router";
import ReportBody from "./ReportBody.vue";

/**
 * Checks of ONE explicit report: ?report=<id> or the Run's initial_report_id
 * (never an implicit "latest").
 */
const props = defineProps<{ run: Run; reportId: string | null }>();
const selected = computed(() => props.reportId ?? props.run.initial_report_id ?? null);
const reports = useApi(() => `reports:${props.run.run_id}`, () => api.reports(props.run.run_id));
const checks = useApi(
  () => (selected.value ? `report-checks:${selected.value}` : null),
  () => api.reportChecks(selected.value!),
);
const choose = (e: Event) =>
  navigate(`${href("runs", props.run.run_id, "checks")}?report=${encodeURIComponent((e.target as HTMLSelectElement).value)}`);
</script>

<template>
  <div>
    <div class="row-between">
      <AsyncView :value="reports" what="Загрузка отчётов">
        <template #default="{ data: list }">
          <label>
            Отчёт
            <select aria-label="Отчёт" :value="selected ?? ''" @change="choose">
              <option v-for="r in list.items" :key="r.report_id" :value="r.report_id">
                {{ r.report_id }} {{ r.report_id === list.initial_report_id ? "(исходный)" : "(повтор проверок)" }} — {{ r.status
                }}{{ r.completeness ? `, ${r.completeness}` : "" }}
              </option>
            </select>
          </label>
        </template>
      </AsyncView>
      <a v-if="selected" class="button" :href="api.reportHtmlUrl(selected)" target="_blank" rel="noopener noreferrer" :download="`${selected}.html`">
        Скачать HTML-отчёт
      </a>
    </div>
    <EmptyView v-if="!selected">У Run нет initial_report_id — отчёт по проверкам не опубликован.</EmptyView>
    <AsyncView v-else :value="checks" what="Загрузка результатов проверок">
      <template #default="{ data: d }">
        <ReportBody v-if="d.report_id === selected" :doc="d" :run-id="run.run_id" />
      </template>
    </AsyncView>
  </div>
</template>
