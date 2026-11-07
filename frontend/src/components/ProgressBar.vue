<script setup lang="ts">
import { computed } from "vue";

/** Determinate only when total is known; otherwise an indeterminate bar (no invented percent). */
const props = defineProps<{ processed?: number | null; total?: number | null }>();
const known = computed(() => typeof props.total === "number" && props.total > 0 && typeof props.processed === "number");
const pct = computed(() => (known.value ? Math.min(100, Math.round((props.processed! / props.total!) * 100)) : 0));
</script>

<template>
  <div class="progress">
    <template v-if="known">
      <progress :max="total!" :value="processed!" aria-label="Прогресс" />
      <span>{{ processed }} / {{ total }} ({{ pct }}%)</span>
    </template>
    <template v-else>
      <progress aria-label="Прогресс (общее число неизвестно)" />
      <span>{{ typeof processed === "number" ? `обработано ${processed}, всего неизвестно` : "прогресс неизвестен" }}</span>
    </template>
  </div>
</template>
