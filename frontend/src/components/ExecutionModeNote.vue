<script setup lang="ts">
import { computed } from "vue";
import { api } from "../api/instance";
import { useApi } from "../composables/useApi";

/** Shows the server's execution mode up front, so a refusal is not a surprise. */
const ready = useApi(() => "ready", () => api.ready());
const kinds = useApi(() => "script-kinds", () => api.scriptKinds());
const flag = computed(() => kinds.data?.find((k) => k.custom_execution_enabled !== undefined)?.custom_execution_enabled);
const mode = computed(() => ready.data?.execution_mode ?? (flag.value === false ? "builtin-only" : flag.value ? "trusted-local" : undefined));
const disabled = computed(() => mode.value === "builtin-only" || flag.value === false);
</script>

<template>
  <div v-if="mode === 'builtin-only'" class="state state-disabled" role="note" data-testid="exec-mode">
    Сервер в режиме <code>builtin-only</code>: исполняются только встроенные процедуры и проверки. Пользовательский код будет сохранён, но
    запуск с ним backend отклонит (политика безопасности). Администратор может включить <code>DD_EXECUTION_MODE=sandboxed</code>
    (песочница ядра) или <code>trusted-local</code> (только 127.0.0.1).
  </div>
  <div v-else-if="mode && disabled" class="state state-disabled" role="note" data-testid="exec-mode">
    Режим сервера: <code>{{ mode }}</code>. Исполнение пользовательского кода выключено. Проверку можно сохранить; для запуска backend должен подтвердить поддержку пользовательских проверок.
  </div>
  <div v-else-if="mode === 'sandboxed'" class="state state-notready" role="note" data-testid="exec-mode">
    Режим исполнения сервера: <code>sandboxed</code>. Пользовательский Python исполняется в песочнице ядра (Landlock + seccomp):
    доступны только stdlib, ядро <code>decision_diff</code>, входы и рабочий каталог своего запуска. Нет сети и сокетов,
    нельзя запускать программы и процессы, читать <code>/proc</code>, БД, чужие запуски и датасеты. Лимиты: время, память,
    размер файла, CPU, число открытых файлов.
  </div>
  <div v-else-if="mode === 'trusted-local'" class="state state-notready" role="note" data-testid="exec-mode">
    Режим исполнения сервера: <code>{{ mode }}</code>. Пользовательский Python исполняется как доверенный локальный код — не изолированная
    песочница.
  </div>
  <div v-else-if="mode" class="state state-ok" role="note" data-testid="exec-mode">
    Режим исполнения: <code>{{ mode }}</code>. Пользовательские проверки выполняет backend; результаты появятся в новом отчёте этого запуска.
  </div>
</template>
