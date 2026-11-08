<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api/instance";
import AppIcon from "../components/AppIcon.vue";
import ErrorView from "../components/ErrorView.vue";
import LoadingView from "../components/LoadingView.vue";

/** Code + params snapshot actually executed for a slot (normalize|compare|segments|aggregate|check-NN). */
const props = defineProps<{ runId: string; slot: string; checkRunId?: string | null }>();
const code = ref<string | null>(null);
const err = ref<unknown>(null);
const dialog = ref<HTMLDialogElement>();
const loading = ref(false);

async function loadCode() {
  if (code.value !== null || loading.value) return;
  loading.value = true;
  err.value = null;
  // An event of a CheckRun refers to that CheckRun's snapshot; the Run's own
  // /code/{slot} would resolve check-NN to the initial CheckRun instead.
  try {
    const c = await (props.checkRunId ? api.checkRunCode(props.checkRunId, props.slot) : api.code(props.runId, props.slot));
    code.value = `# ${c.name} [${c.source}] rev ${c.script_revision} sha256 ${c.code_sha256}\n# params: ${JSON.stringify(c.params)}\n\n${c.code}`;
  } catch (error) {
    err.value = error;
  } finally {
    loading.value = false;
  }
}

function openCode() {
  dialog.value?.showModal();
  void loadCode();
}
</script>

<template>
  <button type="button" class="code-snapshot-trigger" aria-haspopup="dialog" @click="openCode">код {{ slot }}</button>
  <Teleport to="body">
    <dialog ref="dialog" class="code-snapshot-dialog" :aria-label="`Код ${slot}`" @click="event => { if (event.target === dialog) dialog?.close(); }">
      <header class="code-snapshot-header">
        <h2>Код процедуры <code>{{ slot }}</code></h2>
        <button type="button" class="icon-button" aria-label="Закрыть код" autofocus @click="dialog?.close()"><AppIcon name="close" :size="18" /></button>
      </header>
      <div class="code-snapshot-content">
        <p v-if="checkRunId" class="muted">CheckRun <code>{{ checkRunId }}</code></p>
        <ErrorView v-if="err" :error="err" :on-retry="loadCode" />
        <LoadingView v-else-if="code === null" what="Загрузка кода" />
        <pre v-else class="code-view" tabindex="0" aria-label="Исходный код">{{ code }}</pre>
      </div>
    </dialog>
  </Teleport>
</template>
