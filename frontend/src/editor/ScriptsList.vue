<script setup lang="ts">
import { api } from "../api/instance";
import type { Script } from "../api/types";
import AsyncView from "../components/AsyncView.vue";
import AppIcon from "../components/AppIcon.vue";
import { useApi } from "../composables/useApi";
import { href } from "../router";

const scripts = useApi(() => "scripts", () => api.scripts());
const isEmpty = (d: Script[]) => d.length === 0;
</script>

<template>
  <section>
    <div class="page-heading">
      <div><span class="eyebrow">Процедуры и проверки</span><h1>Рабочая область: скрипты</h1><p class="muted">Библиотека процедур и неизменяемые версии Python-кода для анализа.</p></div>
      <a class="button primary" :href="href('scripts', 'new')"><AppIcon name="plus" :size="17" />Новый скрипт</a>
    </div>
    <AsyncView :value="scripts" :is-empty="isEmpty" empty="Скриптов нет.">
      <template #default="{ data: list }">
        <div class="table-wrap"><table class="table" aria-label="Скрипты">
          <thead>
            <tr>
              <th>Название</th>
              <th>Тип</th>
              <th>Источник</th>
              <th>Ревизия</th>
              <th>sha256</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in list" :key="s.script_id">
              <td><a :href="href('scripts', s.script_id)">{{ s.name }}</a></td>
              <td>{{ s.kind }}</td>
              <td>{{ s.source }}</td>
              <td>{{ s.revision }}</td>
              <td><code>{{ s.code_sha256.slice(0, 12) }}</code></td>
            </tr>
          </tbody>
        </table></div>
      </template>
    </AsyncView>
  </section>
</template>
