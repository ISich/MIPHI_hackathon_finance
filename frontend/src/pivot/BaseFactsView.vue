<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api/instance";
import type { PivotFact, PivotFactsPage, Run } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import { useApi } from "../composables/useApi";
import { href } from "../router";
import { FACT_COLUMNS, FACTS_PAGE, factGroup } from "./facts";

/**
 * Fallback while the server rollup is unavailable: pages of D4 base facts
 * (GET /pivot-facts). CNT is per fact and must not be summed — no totals here.
 */
const props = defineProps<{ run: Run }>();
const offset = ref(0);
const onlyDiff = ref(true);
const page = useApi(() => `facts:${props.run.run_id}:${offset.value}`, () => api.pivotFacts(props.run.run_id, offset.value, FACTS_PAGE));
const isEmpty = (p: PivotFactsPage) => p.items.length === 0;
const visible = (p: PivotFactsPage) => (onlyDiff.value ? p.items.filter((f) => Number(f.DIFF_FLAG) === 1) : p.items);
const factHref = (f: PivotFact) => `${href("runs", props.run.run_id, "fact-apps")}?g=${encodeURIComponent(JSON.stringify(factGroup(f)))}&cnt=${f.CNT}`;
</script>

<template>
  <AsyncView :value="page" what="Загрузка базовых фактов" :is-empty="isEmpty" empty="Базовых фактов нет.">
    <template #default="{ data: p }">
      <div>
        <p class="muted">
          Факты {{ p.offset + 1 }}–{{ p.offset + p.items.length }}. CNT — число различных заявок в одном факте; суммировать CNT между строками нельзя,
          поэтому итогов в этом режиме нет.
        </p>
        <label><input v-model="onlyDiff" type="checkbox" /> только факты с DIFF_FLAG=1 (на этой странице)</label>
        <div class="table-wrap">
          <table class="table" aria-label="Базовые факты">
            <thead>
              <tr>
                <th v-for="c in FACT_COLUMNS" :key="c">{{ c }}</th>
                <th>CNT</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(f, i) in visible(p)" :key="i">
                <td v-for="c in FACT_COLUMNS" :key="c">
                  <span v-if="f[c] === ''" class="muted">∅</span>
                  <template v-else>{{ String(f[c] ?? "—") }}</template>
                </td>
                <td class="num"><a :href="factHref(f)" title="Заявки этого факта">{{ f.CNT }}</a></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="pager">
          <button type="button" :disabled="offset === 0" @click="offset = Math.max(0, offset - FACTS_PAGE)">← Назад</button>
          <button type="button" :disabled="p.next_offset === null" @click="offset = p.next_offset ?? offset">Далее →</button>
        </div>
      </div>
    </template>
  </AsyncView>
</template>
