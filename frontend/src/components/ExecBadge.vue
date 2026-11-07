<script setup lang="ts">
defineProps<{ status: string }>();
</script>

<template>
  <span :class="['badge', status === 'SUCCEEDED' ? 'badge-exec-ok' : 'badge-exec-error']">
    {{ status === "SUCCEEDED" ? "исполнена" : `ошибка исполнения: ${status}` }}
  </span>
</template>
