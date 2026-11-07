<script setup lang="ts">
import { computed } from "vue";
import { ApiError } from "../api/client";
import { api } from "../api/instance";
import type { ReportChecks, Run } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import EmptyView from "../components/EmptyView.vue";
import ErrorView from "../components/ErrorView.vue";
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
/**
 * A report is shown only if it belongs to this Run: it must be listed by
 * GET /runs/{id}/reports, and the loaded document must carry this run_id and
 * dataset revision. Otherwise ?report=<other Run's report> would display foreign
 * checks under this Run (with application links pointing into this Run).
 */
const listed = computed(() => (selected.value && reports.data ? reports.data.items.some((r) => r.report_id === selected.value) : undefined));
const checks = useApi(
  () => (selected.value && listed.value ? `report-checks:${selected.value}` : null),
  () => api.reportChecks(selected.value!),
);
const mismatch = (detail: Record<string, unknown>) =>
  new ApiError(0, {
    code: "REPORT_RUN_MISMATCH",
    message: `Отчёт ${selected.value} не относится к Run ${props.run.run_id} — не показываю его проверки.`,
    details: detail,
  });
const listError = computed(() => (listed.value === false ? mismatch({ report_id: selected.value, run_id: props.run.run_id }) : null));
function docError(d: ReportChecks): ApiError | null {
  if (d.report_id === selected.value && d.run_id === props.run.run_id && d.dataset_revision_id === props.run.dataset_revision_id) return null;
  return mismatch({ report_run_id: d.run_id, report_dataset_revision_id: d.dataset_revision_id, run_dataset_revision_id: props.run.dataset_revision_id });
}
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
      <a v-if="selected && listed" class="button" :href="api.reportHtmlUrl(selected)" target="_blank" rel="noopener noreferrer" :download="`${selected}.html`">
        Скачать HTML-отчёт
      </a>
    </div>
    <EmptyView v-if="!selected">У Run нет initial_report_id — отчёт по проверкам не опубликован.</EmptyView>
    <ErrorView v-else-if="listError" :error="listError" />
    <AsyncView v-else-if="listed" :value="checks" what="Загрузка результатов проверок">
      <template #default="{ data: d }">
        <ErrorView v-if="docError(d)" :error="docError(d)" />
        <ReportBody v-else :doc="d" :run-id="run.run_id" />
      </template>
    </AsyncView>
  </div>
</template>
