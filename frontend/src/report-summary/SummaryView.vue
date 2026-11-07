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
const topHref = (path: string) => `${href("runs", props.run.run_id, "pivot")}?rows=PATH&f.PATH=${encodeURIComponent(path)}`;
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
        <template v-if="d.top_paths?.length">
          <h2>Top PATH</h2>
          <div class="table-wrap"><table class="table" aria-label="Top PATH">
            <tbody>
              <tr v-for="t in d.top_paths" :key="t.path">
                <td><a :href="topHref(t.path)">{{ t.path }}</a></td>
                <td class="num">{{ t.changed_apps }}</td>
              </tr>
            </tbody>
          </table></div>
        </template>
        <p v-else class="muted">Top PATH backend пока не отдаёт.</p>
        <h2>Полнота проверок</h2>
        <p data-testid="completeness">
          {{ run.checks_completeness ?? "—" }}{{ run.checks_completeness === "INCOMPLETE" ? " — часть проверок не исполнилась, см. «Проверки»" : ""
          }}{{ run.checks_completeness === "NO_CHECKS_SELECTED" ? " — технический Run без проверок, не доказательство приёмки checks" : "" }}
        </p>
        <template v-if="d.artifacts?.length">
          <h2>Артефакты</h2>
          <div class="table-wrap"><table class="table" aria-label="Артефакты">
            <tbody>
              <tr v-for="a in d.artifacts" :key="a.artifact_id">
                <td>{{ a.kind }}</td>
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
