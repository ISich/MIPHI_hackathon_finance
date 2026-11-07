<script setup lang="ts">
import { computed, ref, shallowRef } from "vue";
import { saveScript } from "../api/actions";
import { api } from "../api/instance";
import type { Script, ScriptKindName } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import ErrorView from "../components/ErrorView.vue";
import ExecutionModeNote from "../components/ExecutionModeNote.vue";
import PythonEditor from "../components/PythonEditor.vue";
import { useApi } from "../composables/useApi";
import { href } from "../router";

const props = defineProps<{ fromId: string | null }>();
const kinds = useApi(() => "script-kinds", () => api.scriptKinds());
const from = useApi(() => (props.fromId ? `script:${props.fromId}` : null), () => api.script(props.fromId!));
const kind = ref<ScriptKindName | null>(null);
const name = ref("");
const code = ref<string | null>(null);
const file = shallowRef<File | null>(null);
const error = ref<unknown>(null);
const saved = shallowRef<Script | null>(null);
const busy = ref(false);

const effKind = computed<ScriptKindName>(() => kind.value ?? from.data?.kind ?? "check");
const spec = computed(() => kinds.data?.find((k) => k.kind === effKind.value));
const text = computed(() => code.value ?? from.data?.code ?? spec.value?.template ?? "");
const effName = computed(() => name.value || (from.data ? `${from.data.name} (копия)` : ""));

function chooseKind(e: Event) {
  kind.value = (e.target as HTMLSelectElement).value as ScriptKindName;
  code.value = null;
  file.value = null;
}
function setText(c: string) {
  code.value = c;
  file.value = null;
}
function onFile(f: File) {
  file.value = f;
  if (!name.value) name.value = f.name.replace(/\.py$/, "");
}
async function save() {
  busy.value = true;
  error.value = null;
  try {
    saved.value = await saveScript(effKind.value, effName.value, text.value, file.value);
  } catch (e) {
    error.value = e;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section>
    <p><a :href="href('scripts')">← Скрипты</a></p>
    <h1>Новый скрипт</h1>
    <ExecutionModeNote />
    <AsyncView :value="kinds" what="Загрузка контрактов">
      <template #default="{ data: list }">
        <div class="form">
          <label>
            Тип (слот)
            <select :value="effKind" @change="chooseKind">
              <option v-for="k in list" :key="k.kind" :value="k.kind">{{ k.kind }}</option>
            </select>
          </label>
          <details v-if="spec" open>
            <summary>Контракт {{ spec.kind }}</summary>
            <p><code>{{ spec.entrypoint }}</code></p>
            <p v-if="spec.output_columns.length">Выходные колонки: {{ spec.output_columns.join(", ") }}</p>
            <button type="button" @click="setText(spec.example)">Вставить пример</button>
            {{ " " }}
            <button type="button" @click="setText(spec.template)">Вставить шаблон</button>
          </details>
          <label>
            Название
            <input :value="effName" required maxlength="120" @input="name = ($event.target as HTMLInputElement).value" />
          </label>
          <PythonEditor :model-value="text" @update:model-value="setText" @file="onFile" />
          <p class="muted" data-testid="script-source">
            Источник:
            <template v-if="file">файл <code>{{ file.name }}</code> (без изменений)</template>
            <template v-else>редактор (workspace)</template>
          </p>
          <ErrorView v-if="error" :error="error" />
          <div v-if="saved" class="state state-ok" role="status">
            Сохранено: <a :href="href('scripts', saved.script_id)">{{ saved.name }}</a> (rev {{ saved.revision }}, sha256
            {{ saved.code_sha256.slice(0, 12) }}).
            {{
              saved.kind === "check"
                ? "Запустите её на завершённом Run во вкладке «Новая проверка» или выберите в новой конфигурации."
                : "Выберите её в слоте новой конфигурации."
            }}
            <a :href="href('runs', 'new')">Новый запуск →</a>
          </div>
          <button type="button" class="primary" :disabled="busy || !text.trim() || !effName.trim()" @click="save">
            {{ busy ? "Сохранение…" : "Сохранить snapshot" }}
          </button>
        </div>
      </template>
    </AsyncView>
  </section>
</template>
