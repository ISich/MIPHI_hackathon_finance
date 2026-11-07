<script setup lang="ts">
import { computed } from "vue";
import type { PivotResponse } from "../api/types";
import { href } from "../router";
import PivotCellLink from "./PivotCellLink.vue";
import { keyLabel, keyStr, type Key } from "./query";

const props = defineProps<{ data: PivotResponse; rows: string[]; cols: string[]; runId: string; backQuery: string }>();
const coordinates = (item: PivotResponse["items"][number], dims: string[]): Key => dims.map(d => item.dimensions[d] ?? null);
const keys = (dims: string[]) => [...new Map(props.data.items.map(item => {
  const key = coordinates(item, dims);
  return [keyStr(key), key] as const;
})).values()];
const rowKeys = computed(() => keys(props.rows));
const colKeys = computed(() => keys(props.cols));
const cellMap = computed(() => new Map(props.data.items.map(item => [
  JSON.stringify([coordinates(item, props.rows), coordinates(item, props.cols)]),
  { count: item.cnt, group: item.group_locator },
])));
const drill = (group: string) => `${href("runs", props.runId, "groups", group)}?back=${encodeURIComponent(props.backQuery)}`;
</script>

<template>
  <div class="table-wrap">
    <p class="muted">Число различных заявок в каждой группе рассчитано сервером. Одна заявка может входить в несколько групп; итоги не суммируются.</p>
    <p v-if="data.total > data.items.length" class="state state-notready">Показана страница групп. Прочерк означает, что ячейки нет на этой странице.</p>
    <table class="table pivot" aria-label="Сводная таблица">
      <thead><tr>
        <th>{{ rows.join(" · ") || "Все" }}</th>
        <th v-for="ck in colKeys" :key="keyStr(ck)">{{ cols.length ? keyLabel(ck) : "Заявок" }}</th>
      </tr></thead>
      <tbody><tr v-for="rk in rowKeys" :key="keyStr(rk)">
        <th>{{ keyLabel(rk) }}</th>
        <td v-for="ck in colKeys" :key="keyStr(ck)" class="num">
          <PivotCellLink :cell="cellMap.get(JSON.stringify([rk, ck]))" :drill="drill" />
        </td>
      </tr></tbody>
    </table>
  </div>
</template>
