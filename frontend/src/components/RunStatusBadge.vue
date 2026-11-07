<script setup lang="ts">
defineProps<{ status: string }>();
</script>

<template>
  <span :class="`badge badge-${status.toLowerCase()}`">{{ status }}</span>
</template>
