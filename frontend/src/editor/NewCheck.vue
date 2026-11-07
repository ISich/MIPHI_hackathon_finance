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
const name = ref("Новая проверка");
const includeExisting = ref(true);
const error = ref<unknown>(null);
const phase = ref<"edit" | "saving" | "running">("edit");
const checkRun = shallowRef<CheckRun | null>(null);
const saved = shallowRef<{ key: string; script: Script } | null>(null);
let crKey: { scriptId: string; checks: string; key: string } | null = null;
let alive = true;
onBeforeUnmount(() => (alive = false));

/**
 * With "include existing" the new report must contain the Run's original checks;
 * if the configuration is not loaded (pending or failed) we refuse to submit
 * instead of silently dropping them.
 */
const configReady = computed(() => !includeExisting.value || (config.data !== undefined && !config.error));
const checkKind = computed(() => kinds.data?.find((k) => k.kind === "check"));
const text = computed(() => code.value ?? checkKind.value?.template ?? "");

function setText(c: string) {
  code.value = c;
  file.value = null; // edited text is a workspace script, not the uploaded file
}
function onFile(f: File) {
  file.value = f;
  name.value = f.name.replace(/\.py$/, "");
}

async function submit() {
  if (phase.value !== "edit" || !configReady.value) return;
  error.value = null;
  phase.value = "saving";
  try {
    // Re-use the saved snapshot if nothing changed since the last (failed) attempt.
    const saveKey = JSON.stringify([name.value, text.value, file.value?.name ?? null]);
    let script = saved.value?.key === saveKey ? saved.value.script : null;
    if (!script) {
      script = await saveScript("check", name.value, text.value, file.value);
      saved.value = { key: saveKey, script };
    }
    const sid = script.script_id;
    const existing: ScriptRef[] = includeExisting.value ? (config.data?.checks ?? []).filter((c) => c.script_id !== sid) : [];
    const checks = [...existing.map((c) => ({ script_id: c.script_id, params: c.params ?? null })), { script_id: sid }];
    const checksKey = JSON.stringify(checks);
    if (crKey?.scriptId !== sid || crKey.checks !== checksKey) crKey = { scriptId: sid, checks: checksKey, key: newIdempotencyKey() };
    let cr = await api.createCheckRun(props.run.run_id, { checks }, crKey.key);
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
        return;
      }
      await new Promise((r) => setTimeout(r, timing.checkRunPollMs));
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
  <div>
    <h2>Новая проверка</h2>
    <ExecutionModeNote />
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
    <label>
      <input v-model="includeExisting" type="checkbox" /> включить в новый отчёт исходные проверки конфигурации{{
        config.data ? ` (${config.data.checks.length})` : ""
      }}
    </label>
    <template v-if="includeExisting && config.error">
      <p class="muted">Не удалось загрузить конфигурацию Run — исходные проверки неизвестны, запуск заблокирован (можно снять галочку выше).</p>
      <ErrorView :error="config.error" :on-retry="config.reload" />
    </template>
    <ErrorView v-if="error" :error="error" />
    <p v-if="saved && error" class="muted">
      Скрипт уже сохранён: <a :href="href('scripts', saved.script.script_id)">{{ saved.script.name }}</a> (rev {{ saved.script.revision }}).
    </p>
    <p v-if="phase === 'running'" role="status">
      Проверки исполняются на сервере… CheckRun <code>{{ checkRun?.check_run_id }}</code>: {{ checkRun?.status ?? "QUEUED" }}
    </p>
    <button type="button" class="primary" :disabled="phase !== 'edit' || !configReady || !text.trim() || !name.trim()" @click="submit">
      {{ phase === "saving" ? "Сохранение…" : "Сохранить и запустить проверки" }}
    </button>
  </div>
</template>
