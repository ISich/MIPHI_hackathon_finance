<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../api/instance";
import ActivityChart from "../components/ActivityChart.vue";
import AppIcon from "../components/AppIcon.vue";
import AsyncView from "../components/AsyncView.vue";
import RunStatusBadge from "../components/RunStatusBadge.vue";
import { useApi, usePolling } from "../composables/useApi";
import { timing } from "../config";
import { href } from "../router";
import { activityByDay, formatDuration, formatRunDate, selectRuns, type RunFilter } from "./presentation";

defineProps<{ overview?: boolean }>();
const runs = useApi(() => "runs", () => api.runsPage());
const query = ref("");
const filter = ref<RunFilter>("all");
const today = ref(new Date());
let dateTimer: ReturnType<typeof setInterval>;
onMounted(() => { dateTimer = setInterval(() => { today.value = new Date(); }, 60_000); });
onUnmounted(() => clearInterval(dateTimer));
const all = computed(() => runs.data?.items ?? []);
const total = computed(() => runs.data?.total ?? 0);
const partial = computed(() => total.value > all.value.length);
const scope = computed(() => partial.value ? `Среди последних ${all.value.length}` : "Все запуски аккаунта");
const filtered = computed(() => selectRuns(all.value, query.value, filter.value));
const days = computed(() => activityByDay(all.value, today.value));
const activeCount = computed(() => all.value.filter(run => run.status === "RUNNING" || run.status === "QUEUED").length);
const metrics = computed(() => [
  { label: "Всего запусков", value: total.value, icon: "runs", detail: "В аккаунте", filter: "all" as const, tone: "neutral" },
  { label: "Завершено", value: all.value.filter(run => run.status === "COMPLETED").length, icon: "check", detail: scope.value, filter: "completed" as const, tone: "success" },
  { label: "В работе", value: activeCount.value, icon: "activity", detail: scope.value, filter: "active" as const, tone: "accent" },
  { label: "С ошибкой", value: all.value.filter(run => run.status === "FAILED").length, icon: "warning", detail: scope.value, filter: "failed" as const, tone: "danger" },
]);
const filters: Array<{ value: RunFilter; label: string }> = [
  { value: "all", label: "Все запуски" }, { value: "active", label: "Активные" }, { value: "completed", label: "Завершённые" }, { value: "failed", label: "С ошибкой" },
];
usePolling(
  () => !!runs.data?.items.some((r) => r.status === "QUEUED" || r.status === "RUNNING"),
  () => timing.listPollMs,
  async () => runs.reload(),
);
function resetFilters() { query.value = ""; filter.value = "all"; }
</script>

<template>
  <section class="runs-screen">
    <div class="page-heading">
      <div><span class="eyebrow">Анализ изменений СПР</span><h1>{{ overview ? 'Обзор рабочего пространства' : 'Запуски' }}</h1><p class="muted">{{ overview ? 'Всё, что происходит с вашими расчётами, — в одном месте.' : 'История расчётов, результаты сравнения и отчёты проверок.' }}</p></div>
      <a class="button primary" :href="href('runs', 'new')"><AppIcon name="plus" :size="17" />Новый запуск</a>
    </div>
    <div class="view-toolbar"><span class="period-label"><AppIcon name="calendar" :size="17" />{{ today.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }) }}</span><span class="toolbar-note"><span class="live-dot" :class="{ 'is-active': activeCount > 0 }" />{{ activeCount ? 'Активные запуски обновляются автоматически' : 'Данные аккаунта' }}</span></div>
    <AsyncView :value="runs" what="Загрузка запусков">
      <template #default>
        <div class="metric-grid" aria-label="Показатели запусков"><button v-for="metric in metrics" :key="metric.label" class="metric-card" :class="`metric-${metric.tone}`" :aria-pressed="filter === metric.filter" @click="filter = metric.filter"><span class="metric-top"><span class="metric-icon"><AppIcon :name="metric.icon" :size="19" /></span><AppIcon name="arrow" :size="16" /></span><span class="metric-label">{{ metric.label }}</span><strong class="metric-value">{{ metric.value.toLocaleString('ru-RU') }}</strong><span class="metric-detail">{{ metric.detail }}</span></button></div>
        <p v-if="partial" class="muted" role="note">Загружены последние {{ all.length }} из {{ total }} запусков. Статусы, график, поиск и фильтры учитывают только эти запуски.</p>
        <ActivityChart v-if="overview" :days="days" :scope="partial ? `По последним ${all.length} запускам` : undefined" />
        <section class="runs-panel" aria-labelledby="runs-table-title">
          <div class="panel-heading"><div><h2 id="runs-table-title">{{ overview ? 'Последние запуски' : 'История запусков' }} <span class="count-badge">{{ all.length }}</span></h2><p class="muted">Выберите запуск, чтобы исследовать изменения и результаты проверок.</p></div><button class="button refresh-button" :disabled="runs.loading" @click="runs.reload()"><AppIcon name="refresh" :size="15" />Обновить</button></div>
          <div class="runs-filters"><div class="filter-tabs" role="group" aria-label="Фильтр статуса"><button v-for="item in filters" :key="item.value" :class="{ selected: filter === item.value }" :aria-pressed="filter === item.value" @click="filter = item.value">{{ item.label }}</button></div><label class="search-field"><AppIcon name="search" :size="16" /><span class="sr-only">Поиск запусков</span><input v-model="query" type="search" placeholder="Поиск по ID, данным…" /></label></div>
        <div v-if="filtered.length" class="table-wrap runs-table-wrap"><table class="table runs-table" aria-label="Список запусков">
          <thead>
            <tr>
              <th>Запуск</th>
              <th>Статус</th>
              <th>Этап</th>
              <th>Конфигурация</th>
              <th>Создан</th>
              <th>Время</th>
              <th><span class="sr-only">Открыть</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in filtered" :key="r.run_id">
              <td><a class="run-id" :href="href('runs', r.run_id)"><span class="run-table-icon"><AppIcon name="runs" :size="16" /></span>{{ r.run_id }}</a><span class="run-dataset">{{ r.dataset_id }}</span></td>
              <td><RunStatusBadge :status="r.status" /></td>
              <td>{{ r.stage ?? "—" }}</td>
              <td><code>{{ r.config_id }}</code></td>
              <td><time :datetime="r.created_at" :title="r.created_at">{{ formatRunDate(r.created_at) }}</time></td>
              <td class="duration-cell">{{ formatDuration(r) }}</td>
              <td><a class="icon-button" :href="href('runs', r.run_id)" :aria-label="`Открыть запуск ${r.run_id}`"><AppIcon name="arrow" :size="17" /></a></td>
            </tr>
          </tbody>
        </table></div>
        <div v-else class="runs-empty"><span class="empty-icon"><AppIcon :name="all.length ? 'search' : 'runs'" :size="26" /></span><h3>{{ all.length ? 'Ничего не найдено' : 'Пока ни одного запуска' }}</h3><p>{{ all.length ? 'Измените запрос или выберите другой статус.' : 'Выберите набор данных и настройте процедуры. Мы покажем ход анализа и сохраним результаты.' }}</p><button v-if="all.length" @click="resetFilters">Сбросить фильтры</button><a v-else class="button primary" :href="href('runs', 'new')"><AppIcon name="plus" :size="16" />Создать первый запуск</a></div>
        <div class="table-footer"><span role="status">Показано {{ filtered.length }} из {{ total }}</span><span>Новые запуски сверху</span></div>
        </section>
        <div v-if="overview" class="overview-note"><AppIcon name="shield" :size="18" /><p>Показатели выше описывают запуски, а не изменения заявок. Результаты сравнения и бизнес-проверок доступны в отчёте каждого запуска.</p><a :href="href('scripts')">К процедурам<AppIcon name="arrow" :size="15" /></a></div>
      </template>
    </AsyncView>
  </section>
</template>
