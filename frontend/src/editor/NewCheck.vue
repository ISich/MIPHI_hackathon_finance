<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef } from "vue";
import { saveScript } from "../api/actions";
import { ApiError, newIdempotencyKey } from "../api/client";
import { api } from "../api/instance";
import type { CheckRun, Run, Script, ScriptRef } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import ErrorView from "../components/ErrorView.vue";
import ExecutionModeNote from "../components/ExecutionModeNote.vue";
import PythonEditor from "../components/PythonEditor.vue";
import { useApi } from "../composables/useApi";
import { timing } from "../config";
import { href, navigate } from "../router";

/**
 * "New check" scenario: editor or .py upload → saved snapshot → POST
 * /api/runs/{id}/check-runs with the Run's check set plus the new one → poll
 * the check-run → open the returned report_id explicitly.
 */
const props = defineProps<{ run: Run }>();
const kinds = useApi(() => "script-kinds", () => api.scriptKinds());
const config = useApi(() => `config:${props.run.config_id}`, () => api.configuration(props.run.config_id));
const code = ref<string | null>(null);
const file = shallowRef<File | null>(null);
const defaultName = "Доля изменённых заявок";
const name = ref(defaultName);
const includeExisting = ref(true);
const error = ref<unknown>(null);
const phase = ref<"edit" | "saving" | "starting" | "running">("edit");
const checkRun = shallowRef<CheckRun | null>(null);
const saved = shallowRef<{ key: string; script: Script } | null>(null);
let crKey: { scriptId: string; checks: string; key: string } | null = null;
let alive = true;
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let cancelPoll: (() => void) | undefined;
onBeforeUnmount(() => {
  alive = false;
  clearTimeout(pollTimer);
  cancelPoll?.();
});

/**
 * With "include existing" the new report must contain the Run's original checks;
 * if the configuration is not loaded (pending or failed) we refuse to submit
 * instead of silently dropping them.
 */
const configReady = computed(() => !includeExisting.value || (config.data !== undefined && !config.error));
const checkKind = computed(() => kinds.data?.find((k) => k.kind === "check"));
const text = computed(() => code.value ?? checkKind.value?.example ?? "");
const snapshotKey = computed(() => JSON.stringify([name.value.trim(), text.value, file.value?.name ?? null]));
const savedCurrent = computed(() => saved.value?.key === snapshotKey.value);
const canSave = computed(() => !!checkKind.value && !kinds.error && !!name.value.trim() && !!text.value.trim() && phase.value === "edit");
const canRun = computed(() => canSave.value && configReady.value && props.run.status === "COMPLETED" && checkKind.value?.custom_execution_enabled === true);

function setText(c: string) {
  code.value = c;
  file.value = null; // edited text is a workspace script, not the uploaded file
}
function onFile(f: File) {
  file.value = f;
  if (!name.value.trim() || name.value === defaultName) name.value = f.name.replace(/\.py$/, "");
}

async function persistScript() {
  const key = snapshotKey.value;
  if (saved.value?.key === key) return saved.value.script;
  const script = await saveScript("check", name.value.trim(), text.value, file.value);
  if (alive) saved.value = { key, script };
  return script;
}

async function saveOnly() {
  if (!canSave.value) return;
  error.value = null;
  phase.value = "saving";
  try {
    await persistScript();
  } catch (e) {
    if (alive) error.value = e;
  } finally {
    if (alive) phase.value = "edit";
  }
}

function nextPoll(): Promise<boolean> {
  return new Promise(resolve => {
    cancelPoll = () => resolve(false);
    pollTimer = setTimeout(() => { cancelPoll = undefined; resolve(true); }, timing.checkRunPollMs);
  });
}

async function submit() {
  if (!canRun.value) return;
  error.value = null;
  checkRun.value = null;
  phase.value = "saving";
  try {
    const script = await persistScript();
    if (!alive) return;
    const sid = script.script_id;
    const existing: ScriptRef[] = includeExisting.value ? (config.data?.checks ?? []).filter((c) => c.script_id !== sid) : [];
    const checks = [...existing.map((c) => ({ script_id: c.script_id, params: c.params ?? null })), { script_id: sid }];
    const checksKey = JSON.stringify(checks);
    if (crKey?.scriptId !== sid || crKey.checks !== checksKey) crKey = { scriptId: sid, checks: checksKey, key: newIdempotencyKey() };
    phase.value = "starting";
    let cr = await api.createCheckRun(props.run.run_id, { checks }, crKey.key);
    if (!alive) return;
    phase.value = "running";
    for (;;) {
      if (!alive) return;
      checkRun.value = cr;
      if (cr.status === "COMPLETED") {
        navigate(`${href("runs", props.run.run_id, "checks")}?report=${encodeURIComponent(cr.report_id)}`);
        return;
      }
      if (cr.status === "FAILED") {
        error.value = cr.error ? new ApiError(0, { code: cr.error.code, message: cr.error.message ?? cr.error.code }) : new Error("CheckRun завершился с ошибкой (FAILED)");
        phase.value = "edit";
        crKey = null; // A retry after a terminal failure must create a fresh execution.
        return;
      }
      if (!await nextPoll() || !alive) return;
      cr = await api.checkRun(cr.check_run_id);
    }
  } catch (e) {
    if (!alive) return;
    error.value = e;
    phase.value = "edit";
  }
}
</script>

<template>
  <section class="new-check-screen">
    <h2>Новая проверка</h2>
    <p class="muted">Проверка использует результаты текущего запуска. Готовый пример ниже считает долю заявок с изменениями; его можно изменить или заменить файлом .py.</p>
    <ExecutionModeNote />
    <form class="form" aria-label="Новая проверка" @submit.prevent="submit">
    <fieldset class="new-check-fields" :disabled="phase !== 'edit'">
    <AsyncView :value="kinds" what="Загрузка контракта проверки">
      <template #default>
        <details v-if="checkKind">
          <summary>Контракт проверки</summary>
          <p><code>{{ checkKind.entrypoint }}</code></p>
          <p>Колонки результата: {{ checkKind.output_columns.join(", ") }}</p>
          <button type="button" @click="setText(checkKind.example)">Вставить пример</button>
          {{ " " }}
          <button type="button" @click="setText(checkKind.template)">Вставить шаблон</button>
        </details>
        <p v-else class="muted">Backend не описал kind=check.</p>
      </template>
    </AsyncView>
    <label>
      Название
      <input v-model="name" maxlength="120" required />
    </label>
    <PythonEditor :model-value="text" label="Код проверки" @update:model-value="setText" @file="onFile" />
    <p class="muted" data-testid="script-source">
      Источник:
      <template v-if="file">файл <code>{{ file.name }}</code> (без изменений)</template>
      <template v-else>редактор (workspace)</template>
    </p>
    <label class="check-option">
      <input v-model="includeExisting" type="checkbox" /> включить в новый отчёт исходные проверки конфигурации{{
        config.data ? ` (${config.data.checks.length})` : ""
      }}
    </label>
    <template v-if="includeExisting && config.error">
      <p class="muted">Не удалось загрузить конфигурацию Run — исходные проверки неизвестны, запуск заблокирован (можно снять галочку выше).</p>
      <ErrorView :error="config.error" :on-retry="config.reload" />
    </template>
    <ErrorView v-if="error" :error="error" />
    </fieldset>
    <p v-if="saved && savedCurrent" class="state state-ok" role="status">
      Проверка сохранена: <a :href="href('scripts', saved.script.script_id)">{{ saved.script.name }}</a> (версия {{ saved.script.revision }}).
    </p>
    <p v-if="phase === 'running'" role="status">
      Проверки исполняются на сервере… CheckRun <code>{{ checkRun?.check_run_id }}</code>: {{ checkRun?.status ?? "QUEUED" }}
    </p>
    <div class="new-check-actions">
      <button type="submit" class="primary" :disabled="!canRun">
        {{ phase === 'saving' ? 'Сохранение…' : phase === 'starting' ? 'Запуск проверок…' : phase === 'running' ? 'Проверки выполняются…' : 'Сохранить и запустить проверки' }}
      </button>
      <button type="button" :disabled="!canSave || savedCurrent" @click="saveOnly">Сохранить проверку</button>
    </div>
    <p v-if="checkKind?.custom_execution_enabled === false" class="muted">Запуск недоступен: сервер разрешает только встроенные проверки. Код можно сохранить и запустить после подключения сервера с исполнением пользовательских проверок.</p>
    <p v-else-if="checkKind && checkKind.custom_execution_enabled === undefined" class="muted">Сервер не сообщил, поддерживает ли он запуск пользовательских проверок. Сохранение кода доступно.</p>
    </form>
  </section>
</template>

<style scoped>
.new-check-screen > .muted { max-width: 820px; }
.new-check-fields { border: 0; padding: 0; gap: 20px; }
.new-check-actions { display: flex; flex-wrap: wrap; gap: 12px; }
</style>
