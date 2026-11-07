<script setup lang="ts" generic="T">
import type { Loadable } from "../composables/useApi";
import EmptyView from "./EmptyView.vue";
import ErrorView from "./ErrorView.vue";
import LoadingView from "./LoadingView.vue";

/** Renders loading / error / empty / content for a Loadable. */
defineProps<{ value: Loadable<T>; isEmpty?: (data: T) => boolean; empty?: string; what?: string }>();
defineSlots<{ default(props: { data: T }): unknown; empty?(): unknown }>();
</script>

<template>
  <ErrorView v-if="value.error" :error="value.error" :on-retry="value.reload" />
  <template v-else-if="value.data === undefined">
    <LoadingView v-if="value.loading" :what="what" />
  </template>
  <EmptyView v-else-if="isEmpty && isEmpty(value.data)">
    <slot name="empty">{{ empty ?? "Пусто" }}</slot>
  </EmptyView>
  <slot v-else :data="value.data" />
</template>
