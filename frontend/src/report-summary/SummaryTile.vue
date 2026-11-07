<script setup lang="ts">
defineProps<{ label: string; value: number | string; testId?: string }>();
</script>

<template>
  <div class="tile" :data-testid="testId">
    <div class="tile-value">{{ value }}</div>
    <div class="tile-label">{{ label }}</div>
  </div>
</template>
