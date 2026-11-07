<script setup lang="ts">
defineProps<{ result: "PASS" | "FAIL"; low: boolean }>();
</script>

<template>
  <span :class="['badge', `badge-${result.toLowerCase()}`, { 'badge-low': low }]" :title="low ? 'LOW confidence' : 'HIGH confidence'">
    {{ result }}{{ low ? " · LOW" : "" }}
  </span>
</template>
