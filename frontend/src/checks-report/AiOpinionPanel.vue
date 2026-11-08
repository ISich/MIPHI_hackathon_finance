<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api/instance";
import type { AiFinding, AiOpinion } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import ErrorView from "../components/ErrorView.vue";
import { useApi, usePolling } from "../composables/useApi";
import { timing } from "../config";

/**
 * FR-024: separate AI opinion block inside the same check report. It is shown
 * next to, never instead of, the deterministic rows and never changes them.
 */
const props = defineProps<{ reportId: string }>();
const view = useApi(() => `ai-opinion:${props.reportId}`, () => api.aiOpinion(props.reportId));
const fresh = ref<AiOpinion | null>(null);
const current = computed<AiOpinion | undefined>(() => (fresh.value?.report_id === props.reportId ? fresh.value : undefined) ?? view.data);
const pending = computed(() => current.value?.status === "PENDING");
usePolling(() => pending.value, () => timing.runPollMs, async () => {
  fresh.value = await api.aiOpinion(props.reportId);
});

const busy = ref(false);
const requestError = ref<unknown>(null);
async function ask(force: boolean) {
  busy.value = true;
  requestError.value = null;
  try {
    fresh.value = await api.requestAiOpinion(props.reportId, force);
  } catch (e) {
    requestError.value = e;
  } finally {
    busy.value = false;
  }
}

const SEVERITY: Record<AiFinding["severity"], { label: string; cls: string }> = {
  info: { label: "к сведению", cls: "ai-sev-info" },
  attention: { label: "обратить внимание", cls: "ai-sev-attention" },
  concern: { label: "тревожный сигнал", cls: "ai-sev-concern" },
};

function factText(id: string): string {
  const f = current.value?.facts?.[id];
  if (!f) return id;
  return Object.entries(f)
    .filter(([k]) => k !== "id")
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join("\n");
}
const dropped = computed(() => current.value?.validation?.dropped?.length ?? 0);
const tokens = computed(() => current.value?.usage?.total_tokens ?? null);
</script>

<template>
  <section class="card ai-opinion" data-testid="ai-opinion" :data-ai-status="current?.status">
    <header class="row-between">
      <h3>Альтернативное мнение ИИ</h3>
      <div v-if="current && current.status !== 'DISABLED'">
        <button v-if="current.status === 'NOT_REQUESTED'" class="primary" :disabled="busy" @click="ask(false)">Получить мнение ИИ</button>
        <button v-else-if="current.status === 'FAILED'" :disabled="busy" @click="ask(false)">Повторить запрос</button>
        <button v-else-if="current.status === 'READY'" :disabled="busy" @click="ask(true)">Запросить заново</button>
      </div>
    </header>
    <p class="muted ai-disclaimer">{{ current?.disclaimer ?? "Мнение языковой модели не меняет результаты проверок." }}</p>
    <ErrorView v-if="requestError" :error="requestError" />
    <AsyncView v-if="!current" :value="view" what="Загрузка статуса ИИ-мнения"><template #default></template></AsyncView>
    <template v-else>
      <div v-if="current.status === 'DISABLED'" class="state state-disabled">
        ИИ-мнение не включено на сервере<template v-if="current.disabled_reason">: {{ current.disabled_reason }}</template>.
      </div>
      <p v-else-if="current.status === 'NOT_REQUESTED'" class="muted">
        Мнение ещё не запрашивалось. В модель уйдут только обезличенные агрегаты, строки проверок без APP_ID и частые изменённые PATH.
      </p>
      <div v-else-if="current.status === 'PENDING'" class="state state-loading">Модель анализирует отчёт… ({{ current.model }})</div>
      <div v-else-if="current.status === 'FAILED'" class="state state-error">
        Мнение не получено: <code>{{ current.error?.code }}</code> {{ current.error?.message }}
        <div class="muted">Числа и PASS/FAIL отчёта от этого не зависят.</div>
      </div>
      <template v-else-if="current.opinion">
        <p class="ai-summary">{{ current.opinion.summary }}</p>
        <ol v-if="current.opinion.findings.length" class="ai-findings">
          <li v-for="(f, i) in current.opinion.findings" :key="i">
            <div>
              <strong>{{ f.title }}</strong>
              <span :class="['ai-sev', SEVERITY[f.severity].cls]">{{ SEVERITY[f.severity].label }}</span>
            </div>
            <div>{{ f.text }}</div>
            <div v-if="f.unverified_numbers.length" class="ai-warn">
              Числа не найдены в переданных фактах: {{ f.unverified_numbers.join(", ") }} — проверьте вручную.
            </div>
            <div class="muted">
              Факты:
              <code v-for="r in f.refs" :key="r" class="ai-ref" :title="factText(r)">{{ r }}</code>
            </div>
          </li>
        </ol>
        <p v-else class="muted">Модель не выделила выводов со ссылками на факты.</p>
        <template v-if="current.opinion.limitations.length">
          <strong>Ограничения</strong>
          <ul>
            <li v-for="(l, i) in current.opinion.limitations" :key="i">{{ l }}</li>
          </ul>
        </template>
        <p class="muted">
          Модель {{ current.model }} · {{ current.duration_seconds }} с<template v-if="tokens !== null"> · {{ tokens }} токенов</template>
          · промпт {{ current.prompt_revision }}<template v-if="dropped"> · отброшено выводов без корректных ссылок: {{ dropped }}</template>
        </p>
      </template>
    </template>
  </section>
</template>

<style scoped>
.ai-opinion { border-style: dashed; }
.ai-opinion h3 { margin: 0; }
.ai-disclaimer { font-size: .8rem; margin: 6px 0 12px; }
.ai-summary { line-height: 1.55; }
.ai-findings { padding-left: 1.2rem; }
.ai-findings li { margin: 10px 0; line-height: 1.5; }
.ai-sev { margin-left: 8px; padding: 1px 7px; border-radius: 10px; font-size: .72rem; border: 1px solid var(--line); }
.ai-sev-info { color: var(--muted); }
.ai-sev-attention { color: var(--warn); background: var(--warn-bg); border-color: var(--warn); }
.ai-sev-concern { color: var(--fail); background: var(--err-bg); border-color: var(--fail); }
.ai-warn { color: var(--warn); font-size: .82rem; }
.ai-ref { margin-right: 6px; cursor: help; }
</style>
