<script setup lang="ts">
import { ref } from "vue";
import { api } from "../api/instance";
import ErrorView from "../components/ErrorView.vue";
import LoadingView from "../components/LoadingView.vue";

/** Code + params snapshot actually executed for a slot (normalize|compare|segments|aggregate|check-NN). */
const props = defineProps<{ runId: string; slot: string }>();
const code = ref<string | null>(null);
const err = ref<unknown>(null);

function onToggle(e: Event) {
  if (!(e.target as HTMLDetailsElement).open || code.value !== null) return;
  api.code(props.runId, props.slot).then(
    (c) => (code.value = `# ${c.name} [${c.source}] rev ${c.script_revision} sha256 ${c.code_sha256}\n# params: ${JSON.stringify(c.params)}\n\n${c.code}`),
    (e2: unknown) => (err.value = e2),
  );
}
</script>

<template>
  <details @toggle="onToggle">
    <summary>код {{ slot }}</summary>
    <ErrorView v-if="err" :error="err" />
    <LoadingView v-else-if="code === null" />
    <pre v-else class="code-view">{{ code }}</pre>
  </details>
</template>
