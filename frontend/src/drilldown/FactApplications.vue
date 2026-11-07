<script setup lang="ts">
import { computed } from "vue";
import { api } from "../api/instance";
import AsyncView from "../components/AsyncView.vue";
import { useApi } from "../composables/useApi";
import { href } from "../router";

const MAX_FACT_APPS = 10000;

/** Drill-down from a D4 base fact (fallback mode): POST /pivot-facts/applications. */
const props = defineProps<{ runId: string; group: string; cnt: number | null; report?: string | null }>();
const backHref = computed(() => href("runs", props.runId, "pivot") + (props.report ? `?report=${encodeURIComponent(props.report)}` : ""));
const parsed = computed<Record<string, unknown> | null>(() => {
  try {
    const v: unknown = JSON.parse(props.group);
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
  } catch {
    return null;
  }
});
const limit = computed(() => Math.min(MAX_FACT_APPS, Math.max(1, props.cnt ?? 200)));
const page = useApi(
  () => (parsed.value ? `fact-apps:${props.runId}:${props.group}:${limit.value}` : null),
  () => api.pivotFactApplications(props.runId, parsed.value!, limit.value),
);
</script>

<template>
  <section>
    <p><a :href="backHref">← К базовым фактам</a></p>
    <h1>Заявки факта</h1>
    <dl v-if="parsed" class="kv">
      <div v-for="(v, k) in parsed" :key="k" class="kv-pair">
        <dt>{{ k }}</dt>
        <dd>{{ v === "" ? "∅ (пусто)" : String(v) }}</dd>
      </div>
    </dl>
    <div v-else class="state state-error">Некорректная ссылка на группу.</div>
    <AsyncView :value="page" what="Загрузка заявок">
      <template #default="{ data: p }">
        <div>
          <p data-testid="group-total">
            Получено заявок: <strong>{{ p.items.length }}</strong>{{ cnt !== null ? `; CNT факта: ${cnt}` : "" }}
            <span v-if="p.total === null" class="muted"> — полный distinct total backend не сообщает{{ p.total_note ? ` (${p.total_note})` : "" }}</span>
            <template v-else>; всего: {{ p.total }}</template>
          </p>
          <ul class="app-list">
            <li v-for="app in p.items" :key="app"><a :href="href('runs', runId, 'apps', app)">{{ app }}</a></li>
          </ul>
        </div>
      </template>
    </AsyncView>
  </section>
</template>
