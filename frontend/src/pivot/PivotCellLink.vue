<script setup lang="ts">
defineProps<{ cell?: { count: number; group: string }; drill: (group: string) => string }>();
</script>

<template>
  <a v-if="cell && cell.count > 0" :href="drill(cell.group)" title="Открыть заявки группы">{{ cell.count }}</a>
  <span v-else class="muted">0</span>
</template>
