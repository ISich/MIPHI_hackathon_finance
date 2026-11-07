<script setup lang="ts">
import { computed } from "vue";
import type { PivotResponse } from "../api/types";
import { href } from "../router";
import PivotCellLink from "./PivotCellLink.vue";
import { keyLabel, keyStr } from "./query";

const props = defineProps<{ data: PivotResponse; runId: string; backQuery: string }>();
const cellMap = computed(() => {
  const m = new Map<string, { count: number; group: string }>();
  for (const c of props.data.cells) m.set(keyStr(c.row) + "|" + keyStr(c.col), c);
  return m;
});
const hasCols = computed(() => props.data.cols.length > 0);
const colKeys = computed(() => (props.data.col_totals.length ? props.data.col_totals.map((t) => t.key) : [[]]));
const drill = (group: string) => `${href("runs", props.runId, "groups", group)}?back=${encodeURIComponent(props.backQuery)}`;
</script>

<template>
  <div class="table-wrap">
    <p class="muted">
      Значения — число различных заявок (COUNT DISTINCT APP_ID), посчитано сервером. Итоги не являются суммой ячеек: одна заявка может попасть в
      несколько групп.
    </p>
    <p v-if="data.truncated" class="state state-notready">Результат усечён сервером.</p>
    <div class="table-wrap"><table class="table pivot" aria-label="Сводная таблица">
      <thead>
        <tr>
          <th>{{ data.rows.join(" · ") || "—" }}</th>
          <template v-if="hasCols">
            <th v-for="k in colKeys" :key="keyStr(k)">{{ keyLabel(k) }}</th>
            <th>Итого</th>
          </template>
          <th v-else>Заявок</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="rt in data.row_totals" :key="keyStr(rt.key)">
          <th>{{ keyLabel(rt.key) }}</th>
          <template v-if="hasCols">
            <td v-for="ck in colKeys" :key="keyStr(ck)" class="num">
              <PivotCellLink :cell="cellMap.get(keyStr(rt.key) + '|' + keyStr(ck))" :drill="drill" />
            </td>
          </template>
          <td class="num total"><PivotCellLink :cell="rt" :drill="drill" /></td>
        </tr>
      </tbody>
      <tfoot>
        <tr>
          <th>Итого</th>
          <template v-if="hasCols">
            <td v-for="t in data.col_totals" :key="keyStr(t.key)" class="num total"><PivotCellLink :cell="t" :drill="drill" /></td>
          </template>
          <td class="num total" data-testid="grand-total"><PivotCellLink :cell="data.grand_total" :drill="drill" /></td>
        </tr>
      </tfoot>
    </table></div>
  </div>
</template>
