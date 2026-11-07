<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api/instance";
import ErrorView from "../components/ErrorView.vue";
import LoadingView from "../components/LoadingView.vue";

/** Code + params snapshot actually executed for a slot (normalize|compare|segments|aggregate|check-NN). */
const props = defineProps<{ runId: string; slot: string; checkRunId?: string | null }>();
const code = ref<string | null>(null);
const err = ref<unknown>(null);

function onToggle(e: Event) {
  if (!(e.target as HTMLDetailsElement).open || code.value !== null) return;
  // An event of a CheckRun refers to that CheckRun's snapshot; the Run's own
  // /code/{slot} would resolve check-NN to the initial CheckRun instead.
  const load = props.checkRunId ? api.checkRunCode(props.checkRunId, props.slot) : api.code(props.runId, props.slot);
  load.then(
    (c) => (code.value = `# ${c.name} [${c.source}] rev ${c.script_revision} sha256 ${c.code_sha256}\n# params: ${JSON.stringify(c.params)}\n\n${c.code}`),
    (e2: unknown) => (err.value = e2),
  );
}
</script>

<template>
  <details @toggle="onToggle">
    <summary>код {{ slot }}</summary>
    <div v-if="checkRunId" class="muted">CheckRun <code>{{ checkRunId }}</code></div>
    <ErrorView v-if="err" :error="err" />
    <LoadingView v-else-if="code === null" />
    <pre v-else class="code-view">{{ code }}</pre>
  </details>
</template>
