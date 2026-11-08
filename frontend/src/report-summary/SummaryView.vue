<script setup lang="ts">
import { api } from "../api/instance";
import type { Run } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import { useApi } from "../composables/useApi";
import { href } from "../router";
import SummaryTile from "./SummaryTile.vue";

const props = defineProps<{ run: Run }>();
const s = useApi(() => `summary:${props.run.run_id}`, () => api.summary(props.run.run_id));
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const topHref = (path: string) => `${href("runs", props.run.run_id, "pivot")}?rows=PATH&f.PATH=${encodeURIComponent(path)}&f.DIFF_FLAG=1`;
const artifactDetails: Record<string, { filename: string; description: string }> = {
  normalized_union: { filename: "normalized_union.csv", description: "Поля и значения исходных документов в едином формате, с отметкой «до» или «после»." },
  comparison: { filename: "comparison.csv", description: "Сравнение полей заявок: путь к полю, значения до и после, тип изменения." },
  segments: { filename: "segments.csv", description: "Признаки заявок для группировки и анализа: решения, продукты, модели и другие параметры." },
  pivot_facts: { filename: "pivot_facts.csv", description: "Данные для сводных таблиц: группы полей, значения и количество уникальных заявок." },
  summary: { filename: "summary.json", description: "Итоговые показатели запуска: количество заявок, изменений и смен решений." },
  mart: { filename: "mart.duckdb", description: "База результатов для сводных таблиц, фильтрации и детализации по заявкам." },
};
</script>

<template>
  <AsyncView :value="s" what="Загрузка сводки">
    <template #default="{ data: d }">
      <div v-if="d.run_id === run.run_id">
        <p class="muted">
          Числа получены backend из расчёта этого Run (dataset revision <code>{{ d.dataset_revision_id ?? run.dataset_revision_id }}</code>).
        </p>
        <div class="tiles" aria-label="Итоговые показатели">
          <SummaryTile label="Заявок" :value="d.total_apps" test-id="tile-total" />
          <SummaryTile label="Изменилось заявок" :value="d.changed_apps" test-id="tile-changed" />
          <SummaryTile label="Смена решения" :value="d.decision_changed_apps" test-id="tile-decision" />
          <SummaryTile label="Изменённых атрибутов" :value="d.changed_attributes" />
          <SummaryTile label="Approval rate до → после" :value="`${pct(d.approval_rate_before)} → ${pct(d.approval_rate_after)}`" />
        </div>
        <h2>Типы изменений</h2>
        <p class="muted">Число строк сравнения (атрибутов) по типу, не число заявок.</p>
        <div class="table-wrap"><table class="table" aria-label="Типы изменений">
          <tbody>
            <tr v-for="(v, k) in d.change_types" :key="k">
              <th>{{ k }}</th>
              <td class="num">{{ v }}</td>
            </tr>
          </tbody>
        </table></div>
        <section class="summary-paths">
        <h2>Чаще всего изменённые поля</h2>
        <template v-if="d.top_paths?.length">
          <p class="muted">До 20 полей по числу изменённых заявок. Нажмите на путь к полю, чтобы открыть подробности.</p>
          <div class="table-wrap"><table class="table" aria-label="Чаще всего изменённые поля">
            <thead><tr><th>Путь к полю</th><th class="num">Изменённых заявок</th></tr></thead>
            <tbody>
              <tr v-for="t in d.top_paths" :key="t.path">
                <td><a :href="topHref(t.path)">{{ t.path }}</a></td>
                <td class="num">{{ t.changed_apps }}</td>
              </tr>
            </tbody>
          </table></div>
        </template>
        <p v-else-if="d.top_paths" class="muted">Изменений полей не обнаружено.</p>
        <p v-else class="muted">Список изменённых полей недоступен для этого запуска.</p>
        </section>
        <h2>Полнота проверок</h2>
        <p data-testid="completeness">
          {{ run.checks_completeness ?? "—" }}{{ run.checks_completeness === "INCOMPLETE" ? " — часть проверок не исполнилась, см. «Проверки»" : ""
          }}{{ run.checks_completeness === "NO_CHECKS_SELECTED" ? " — технический Run без проверок, не доказательство приёмки checks" : "" }}
        </p>
        <template v-if="d.artifacts?.length">
          <h2>Артефакты</h2>
          <div class="table-wrap"><table class="table" aria-label="Артефакты">
            <thead><tr><th>Файл и описание</th><th class="num">Строк</th><th class="num">Размер</th><th>Скачать</th></tr></thead>
            <tbody>
              <tr v-for="a in d.artifacts" :key="a.artifact_id">
                <td><code>{{ artifactDetails[a.kind]?.filename ?? a.kind }}</code><p class="artifact-description">{{ artifactDetails[a.kind]?.description ?? 'Дополнительный файл результатов этого запуска.' }}</p></td>
                <td class="num">{{ a.rows ?? "—" }} строк</td>
                <td class="num">{{ a.bytes }} байт</td>
                <td><a :href="a.download">скачать</a></td>
              </tr>
            </tbody>
          </table></div>
        </template>
      </div>
    </template>
  </AsyncView>
</template>

<style scoped>
.summary-paths { margin-block: 24px; }
</style>
