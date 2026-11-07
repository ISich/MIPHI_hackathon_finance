<script setup lang="ts">
import { computed, nextTick, ref } from "vue";

/**
 * Plain textarea code editor (Tab inserts 4 spaces) + .py upload.
 * Code is never executed in the browser; it is only sent to the backend.
 */
const props = withDefaults(defineProps<{ modelValue: string; label?: string }>(), { label: "Код Python" });
const emit = defineEmits<{
  "update:modelValue": [code: string];
  /** The uploaded file; any later manual edit means the code is no longer that file. */
  file: [file: File];
}>();

const MAX_UPLOAD_BYTES = 256 * 1024;
const fileError = ref<string | null>(null);
const area = ref<HTMLTextAreaElement | null>(null);
const lines = computed(() => props.modelValue.split("\n").length);
const bytes = computed(() => new Blob([props.modelValue]).size);

function onKeydown(e: KeyboardEvent) {
  if (e.key !== "Tab" || e.shiftKey) return;
  e.preventDefault();
  const el = e.target as HTMLTextAreaElement;
  const s = el.selectionStart;
  emit("update:modelValue", props.modelValue.slice(0, s) + "    " + props.modelValue.slice(el.selectionEnd));
  void nextTick(() => {
    if (area.value) area.value.selectionStart = area.value.selectionEnd = s + 4;
  });
}

async function onUpload(e: Event) {
  fileError.value = null;
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!/^[A-Za-z0-9_-]{1,80}\.py$/.test(file.name)) {
    fileError.value = "Нужен файл .py с простым именем (латиница, цифры, _ и -).";
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    fileError.value = `Файл больше ${MAX_UPLOAD_BYTES / 1024} КБ.`;
    return;
  }
  const text = await file.text();
  emit("update:modelValue", text);
  emit("file", file);
}
</script>

<template>
  <div class="editor">
    <label class="editor-label">
      {{ label }}
      <textarea
        ref="area"
        class="code"
        spellcheck="false"
        :value="modelValue"
        :rows="Math.min(30, Math.max(12, lines + 1))"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
        @keydown="onKeydown"
      />
    </label>
    <div class="editor-bar">
      <label class="file-btn">
        Загрузить .py
        <input type="file" accept=".py,text/x-python" data-testid="py-upload" @change="onUpload" />
      </label>
      <span class="muted">{{ lines }} строк, {{ bytes }} байт</span>
    </div>
    <div v-if="fileError" class="state state-error" role="alert">{{ fileError }}</div>
  </div>
</template>
