<script setup lang="ts">
import { api } from "../api/instance";
import AsyncView from "../components/AsyncView.vue";
import { useApi } from "../composables/useApi";
import { href } from "../router";

const props = defineProps<{ scriptId: string }>();
const s = useApi(() => `script:${props.scriptId}`, () => api.script(props.scriptId));
</script>

<template>
  <section>
    <p><a :href="href('scripts')">← Скрипты</a></p>
    <AsyncView :value="s">
      <template #default="{ data: d }">
        <div>
          <h1>{{ d.name }}</h1>
          <p class="muted">{{ d.kind }} · {{ d.source }} · rev {{ d.revision }} · sha256 {{ d.code_sha256 }}</p>
          <pre class="code-view">{{ d.code ?? "(код недоступен)" }}</pre>
          <a class="button" :href="`${href('scripts', 'new')}?from=${encodeURIComponent(d.script_id)}`">Создать изменённую копию</a>
        </div>
      </template>
    </AsyncView>
  </section>
</template>
