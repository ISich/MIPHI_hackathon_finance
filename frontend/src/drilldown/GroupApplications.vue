<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api } from "../api/instance";
import AsyncView from "../components/AsyncView.vue";
import { useApi } from "../composables/useApi";
import { appHref, href } from "../router";

const PAGE_SIZE = 50;
const props = defineProps<{ runId: string; group: string; back: string }>();
const offset = ref(0);
watch(() => props.group, () => (offset.value = 0));
const page = useApi(
  () => `group:${props.runId}:${props.group}:${offset.value}`,
  () => api.groupApplications(props.runId, props.group, offset.value, PAGE_SIZE),
);
const backHref = computed(() => `${href("runs", props.runId, "pivot")}${props.back ? `?${props.back}` : ""}`);
const self = computed(() => `${href("runs", props.runId, "groups", props.group)}?back=${encodeURIComponent(props.back)}`);
const toApp = (app: string) => appHref(props.runId, app, self.value);
</script>

<template>
  <section>
    <p><a :href="backHref">← К сводной (фильтры сохранены)</a></p>
    <h1>Заявки группы</h1>
    <AsyncView :value="page" what="Загрузка заявок">
      <template #default="{ data: p }">
        <div>
          <p data-testid="group-total">
            Всего различных заявок: <strong>{{ p.total ?? "не сообщено backend" }}</strong
            >{{ p.items.length ? `; показаны ${offset + 1}–${offset + p.items.length}` : "" }}
          </p>
          <p v-if="p.items.length === 0" class="muted">На этой странице заявок нет.</p>
          <ul class="app-list">
            <li v-for="app in p.items" :key="app"><a :href="toApp(app)">{{ app }}</a></li>
          </ul>
          <div class="pager">
            <button type="button" :disabled="offset === 0" @click="offset = Math.max(0, offset - PAGE_SIZE)">← Назад</button>
            <button
              type="button"
              :disabled="p.total === null ? p.items.length < PAGE_SIZE : offset + PAGE_SIZE >= p.total"
              @click="offset = offset + PAGE_SIZE"
            >
              Далее →
            </button>
          </div>
        </div>
      </template>
    </AsyncView>
  </section>
</template>
