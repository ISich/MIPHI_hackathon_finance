<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api/instance";
import type { ComparisonRow } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import { useApi } from "../composables/useApi";
import { href } from "../router";

const props = defineProps<{ runId: string; appId: string; group: string | null; back: string }>();
const onlyDiff = ref(true);
const app = useApi(() => `app:${props.runId}:${props.appId}`, () => api.application(props.runId, props.appId));
const rowsOf = (rows: ComparisonRow[]) => (onlyDiff.value ? rows.filter((r) => Number(r.DIFF_FLAG) === 1) : rows);
</script>

<template>
  <section>
    <p>
      <a v-if="group" :href="`${href('runs', runId, 'groups', group)}?back=${encodeURIComponent(back)}`">← К заявкам группы</a>
      <a v-else :href="href('runs', runId, 'pivot')">← К сводной</a>
    </p>
    <h1>Заявка <code>{{ appId }}</code></h1>
    <AsyncView :value="app" what="Загрузка заявки">
      <template #default="{ data: d }">
        <div v-if="d.run_id === runId">
          <h2>Сегменты</h2>
          <dl class="kv">
            <div v-for="(v, k) in d.segment" :key="k" class="kv-pair">
              <dt>{{ k }}</dt>
              <dd>{{ v === null || v === undefined ? "—" : String(v) }}</dd>
            </div>
          </dl>
          <h2>Атрибуты BEFORE / AFTER</h2>
          <label><input v-model="onlyDiff" type="checkbox" /> только различия</label>
          <div class="table-wrap">
            <table class="table" aria-label="Сравнение атрибутов">
              <thead>
                <tr>
                  <th>PATH</th>
                  <th>ARRAY_KEY</th>
                  <th>BEFORE</th>
                  <th>AFTER</th>
                  <th>Тип</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in rowsOf(d.comparison)" :key="`${r.PATH}|${r.ARRAY_KEY}`" :class="`ct-${r.CHANGE_TYPE.toLowerCase()}`">
                  <td>{{ r.PATH }}</td>
                  <td>{{ r.ARRAY_KEY }}</td>
                  <td><span v-if="r.CHANGE_TYPE === 'ATTRIBUTE_NEW'" class="muted">(нет)</span><template v-else>{{ r.VALUE_BEFORE }}</template></td>
                  <td><span v-if="r.CHANGE_TYPE === 'ATTRIBUTE_LOST'" class="muted">(нет)</span><template v-else>{{ r.VALUE_AFTER }}</template></td>
                  <td>{{ r.CHANGE_TYPE }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="rowsOf(d.comparison).length === 0" class="muted">Различий нет.</p>
        </div>
      </template>
    </AsyncView>
  </section>
</template>
