<script setup lang="ts">
import type { CheckRow } from "../api/types";
import ResultBadge from "../components/ResultBadge.vue";
import { appHref } from "../router";

defineProps<{ rows: CheckRow[]; runId: string; label: string; returnTo: string }>();
</script>

<template>
  <div class="table-wrap">
    <table class="table" :aria-label="label">
      <thead>
        <tr>
          <th>Результат</th>
          <th>SOURCE</th>
          <th>ARGUMENT</th>
          <th>CNT / TOTAL</th>
          <th>METRIC</th>
          <th>Примеры APP_ID</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in rows" :key="i" :class="{ low: r.CONFIDENCE === 'LOW' }" :data-result="r.RESULT" :data-confidence="r.CONFIDENCE">
          <td><ResultBadge :result="r.RESULT" :low="r.CONFIDENCE === 'LOW'" /></td>
          <td>{{ r.SOURCE }}</td>
          <td>
            <template v-if="r.ARGUMENT">{{ r.ARGUMENT }}</template>
            <span v-else class="muted">—</span>
          </td>
          <td class="num">{{ r.CNT }} / {{ r.TOTAL }}</td>
          <td class="num">{{ r.METRIC }}</td>
          <td>
            <template v-if="r.APP_IDS.length">
              <span class="muted">{{ r.APP_IDS.length }} пример(ов) из {{ r.CNT }}: </span>
              <a v-for="a in r.APP_IDS" :key="a" :href="appHref(runId, a, returnTo)" class="app-chip">{{ a }}</a>
            </template>
            <span v-else class="muted">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
