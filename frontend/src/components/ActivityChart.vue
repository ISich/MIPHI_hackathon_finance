<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ days: Array<{ label: string; count: number }> }>();
const maximum = computed(() => Math.max(1, ...props.days.map(day => day.count)));
const total = computed(() => props.days.reduce((sum, day) => sum + day.count, 0));
</script>

<template>
  <section class="activity-panel" aria-labelledby="activity-title">
    <div class="panel-heading"><div><span class="eyebrow">Активность запусков</span><h2 id="activity-title">История анализа <span class="subtle-badge">7 дней</span></h2></div><span class="chart-legend"><span />Созданные запуски</span></div>
    <div class="activity-chart" role="img" :aria-label="`Запуски за последние 7 дней: ${days.map(day => `${day.label}: ${day.count}`).join(', ')}`">
      <div class="chart-grid"><span>{{ maximum }}</span><span>{{ maximum > 1 ? Math.floor(maximum / 2) : '' }}</span><span>0</span></div>
      <div class="chart-bars"><div v-for="day in days" :key="day.label" class="chart-column"><span v-if="day.count" class="bar-value">{{ day.count }}</span><div class="chart-bar" :class="{ 'bar-empty': day.count === 0 }" :style="{ height: `${Math.max(1, day.count / maximum * 100)}%` }" :title="`${day.label}: ${day.count}`" /><span class="bar-label">{{ day.label }}</span></div></div>
      <div v-if="total === 0" class="chart-empty"><span>История начинается с первого запуска</span><small>Здесь появится активность анализа за неделю</small></div>
    </div>
    <div class="chart-caption"><span>По времени создания · часовой пояс браузера</span><span>{{ total }} за 7 дней</span></div>
  </section>
</template>
