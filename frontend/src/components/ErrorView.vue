<script setup lang="ts">
import { computed } from "vue";
import { ApiError } from "../api/client";

/** Uniform error view: machine code, message, request id; distinguishes not-ready/forbidden/not-found/disabled. */
const props = defineProps<{ error: unknown; onRetry?: () => void }>();

const view = computed(() => {
  const e = props.error;
  if (!(e instanceof ApiError)) return null;
  let title = "Ошибка";
  let kind = "error";
  if (e.isNotReady) [title, kind] = ["Ещё не готово", "notready"];
  else if (e.isExecutionDisabled) [title, kind] = ["Исполнение пользовательского Python выключено на сервере", "disabled"];
  else if (e.isForbidden) [title, kind] = ["Нет доступа", "forbidden"];
  else if (e.isNotFound) [title, kind] = ["Не найдено (или нет доступа)", "notfound"];
  const details = Object.keys(e.details).length ? JSON.stringify(e.details, null, 2) : null;
  return { e, title, kind, details };
});
const plain = computed(() => (props.error instanceof Error ? props.error.message : String(props.error)));
</script>

<template>
  <div v-if="view" :class="`state state-${view.kind}`" role="alert" :data-error-code="view.e.code">
    <strong>{{ view.title }}</strong>
    <div>
      <code>{{ view.e.code }}</code> {{ view.e.status ? `(HTTP ${view.e.status})` : "" }}: {{ view.e.message }}
    </div>
    <pre v-if="view.details" class="details">{{ view.details }}</pre>
    <div v-if="view.e.requestId" class="muted">request_id: {{ view.e.requestId }}</div>
    <button v-if="onRetry" type="button" @click="onRetry()">Повторить</button>
  </div>
  <div v-else class="state state-error" role="alert">
    <strong>Ошибка</strong>
    <div>{{ plain }}</div>
  </div>
</template>
