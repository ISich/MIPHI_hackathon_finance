<script setup lang="ts">
import { api } from "../api/instance";
import AsyncView from "../components/AsyncView.vue";
import RunStatusBadge from "../components/RunStatusBadge.vue";
import { useApi, usePolling } from "../composables/useApi";
import { timing } from "../config";
import { href } from "../router";
import type { Run } from "../api/types";

const runs = useApi(() => "runs", () => api.runs());
usePolling(
  () => !!runs.data?.some((r) => r.status === "QUEUED" || r.status === "RUNNING"),
  () => timing.listPollMs,
  async () => runs.reload(),
);
const isEmpty = (d: Run[]) => d.length === 0;
</script>

<template>
  <section>
    <div class="row-between">
      <h1>Запуски</h1>
      <a class="button primary" :href="href('runs', 'new')">Новый запуск</a>
    </div>
    <AsyncView :value="runs" what="Загрузка запусков" :is-empty="isEmpty" empty="Запусков пока нет.">
      <template #default="{ data }">
        <table class="table" aria-label="Список запусков">
          <thead>
            <tr>
              <th>Run</th>
              <th>Статус</th>
              <th>Этап</th>
              <th>Конфигурация</th>
              <th>Создан</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in data" :key="r.run_id">
              <td><a :href="href('runs', r.run_id)">{{ r.run_id }}</a></td>
              <td><RunStatusBadge :status="r.status" /></td>
              <td>{{ r.stage ?? "—" }}</td>
              <td>{{ r.config_id }}</td>
              <td>{{ r.created_at }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </AsyncView>
  </section>
</template>
