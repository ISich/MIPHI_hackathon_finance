<script setup lang="ts">
import { computed, ref } from "vue";
import { newIdempotencyKey } from "../api/client";
import { api } from "../api/instance";
import { PROCEDURE_SLOTS, type Configuration, type Dataset, type ProcedureSlot, type Script } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import ErrorView from "../components/ErrorView.vue";
import { useApi } from "../composables/useApi";
import { href, navigate } from "../router";

/**
 * Configuration screen: dataset + one procedure per slot (built-in or a saved
 * workspace/.py script) + selected checks → POST configurations → POST runs.
 */
const datasets = useApi(() => "datasets", () => api.datasets());
const scripts = useApi(() => "scripts", () => api.scripts());
const configs = useApi(() => "configurations", () => api.configurations());

const mode = ref<"new" | "saved">("new");
const savedId = ref("");
const name = ref("Конфигурация");
const datasetId = ref("");
const slots = ref<Partial<Record<ProcedureSlot, string>>>({});
const checks = ref<Set<string> | null>(null);
const error = ref<unknown>(null);
const busy = ref(false);
// Retry safety: the same form state reuses the already created configuration and
// the same Idempotency-Key, so a retried submit (e.g. after a network error)
// replays the accepted Run instead of silently creating a duplicate.
let attempt: { form: string; configId?: string; key: string } | null = null;

const byKind = computed(() => {
  const m: Record<string, Script[]> = {};
  for (const s of scripts.data ?? []) (m[s.kind] ??= []).push(s);
  return m;
});
const checkScripts = computed(() => byKind.value["check"] ?? []);
const selectedChecks = computed(() => checks.value ?? new Set(checkScripts.value.filter((s) => s.shared).map((s) => s.script_id)));

function toggleCheck(id: string, on: boolean) {
  const next = new Set(selectedChecks.value);
  if (on) next.add(id);
  else next.delete(id);
  checks.value = next;
}
const lastRev = (d: Dataset) => d.revisions[d.revisions.length - 1];
const noConfigs = (d: Configuration[]) => d.length === 0;
const noDatasets = (d: Dataset[]) => d.length === 0;

async function submit() {
  if (busy.value) return;
  error.value = null;
  busy.value = true;
  try {
    const cfgReq = {
      name: name.value,
      dataset_id: datasetId.value,
      slots: Object.fromEntries(
        Object.entries(slots.value)
          .filter(([, v]) => v)
          .map(([k, v]) => [k, { script_id: v! }]),
      ),
      checks: [...selectedChecks.value].sort().map((script_id) => ({ script_id })),
    };
    const form = JSON.stringify(mode.value === "new" ? cfgReq : { savedId: savedId.value });
    if (attempt?.form !== form) attempt = { form, key: newIdempotencyKey() };
    const a = attempt;
    if (mode.value === "saved") a.configId = savedId.value;
    if (!a.configId) a.configId = (await api.createConfiguration(cfgReq)).config_id;
    const run = await api.createRun({ configuration_id: a.configId }, a.key);
    navigate(href("runs", run.run_id));
  } catch (err) {
    error.value = err;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section>
    <h1>Новый запуск</h1>
    <form class="form" aria-label="Новый запуск" @submit.prevent="submit">
      <fieldset>
        <legend>Источник конфигурации</legend>
        <label><input v-model="mode" type="radio" name="mode" value="new" /> Новая конфигурация</label>
        <label><input v-model="mode" type="radio" name="mode" value="saved" /> Сохранённая</label>
      </fieldset>

      <AsyncView v-if="mode === 'saved'" :value="configs" :is-empty="noConfigs" empty="Сохранённых конфигураций нет.">
        <template #default="{ data: list }">
          <label>
            Конфигурация
            <select v-model="savedId" required>
              <option value="">— выберите —</option>
              <option v-for="c in list" :key="c.config_id" :value="c.config_id">{{ c.name }} ({{ c.config_id }})</option>
            </select>
          </label>
        </template>
      </AsyncView>
      <template v-else>
        <label>
          Название
          <input v-model="name" required maxlength="120" />
        </label>
        <AsyncView :value="datasets" what="Загрузка наборов" :is-empty="noDatasets" empty="Нет доступных наборов данных.">
          <template #default="{ data: list }">
            <label>
              Набор данных
              <select v-model="datasetId" required>
                <option value="">— выберите —</option>
                <option v-for="d in list" :key="d.dataset_id" :value="d.dataset_id">
                  {{ d.name }}{{ lastRev(d) ? ` — пар: ${lastRev(d)!.pairs}` : "" }}
                </option>
              </select>
            </label>
          </template>
        </AsyncView>
        <AsyncView :value="scripts" what="Загрузка процедур">
          <template #default>
            <fieldset>
              <legend>Процедуры по слотам</legend>
              <label v-for="slot in PROCEDURE_SLOTS" :key="slot">
                {{ slot }}
                <select v-model="slots[slot]" :aria-label="`Процедура ${slot}`">
                  <option :value="undefined">встроенная (по умолчанию)</option>
                  <option v-for="s in byKind[slot] ?? []" :key="s.script_id" :value="s.script_id">
                    {{ s.name }} [{{ s.source }}{{ s.source !== "builtin" ? `, rev ${s.revision}` : "" }}]
                  </option>
                </select>
              </label>
              <p class="muted">
                Свою процедуру создайте в <a :href="href('scripts', 'new')">рабочей области</a> — она появится в списке слота.
              </p>
            </fieldset>
            <fieldset>
              <legend>Проверки</legend>
              <p v-if="checkScripts.length === 0" class="muted">Проверок нет.</p>
              <label v-for="s in checkScripts" :key="s.script_id" class="check-option">
                <input
                  type="checkbox"
                  :checked="selectedChecks.has(s.script_id)"
                  @change="toggleCheck(s.script_id, ($event.target as HTMLInputElement).checked)"
                />
                {{ s.name }} <span class="muted">[{{ s.source }}]</span>
              </label>
            </fieldset>
          </template>
        </AsyncView>
      </template>

      <ErrorView v-if="error" :error="error" />
      <button type="submit" class="primary" :disabled="busy">{{ busy ? "Запуск…" : "Сохранить конфигурацию и запустить" }}</button>
    </form>
  </section>
</template>
