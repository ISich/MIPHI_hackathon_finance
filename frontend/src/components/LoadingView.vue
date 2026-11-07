<script setup lang="ts">
withDefaults(defineProps<{ what?: string }>(), { what: "Загрузка" });
</script>

<template>
  <div class="state state-loading" role="status" aria-live="polite">{{ what }}…</div>
</template>
