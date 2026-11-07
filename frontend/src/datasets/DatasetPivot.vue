<script setup lang="ts">
import { computed } from "vue";
import { buildPivot, display, formatNumber, operations, type PivotConfig, type TableDataset } from "./model";
import { downloadCsv } from "./files";
import AppIcon from "../components/AppIcon.vue";
const props = defineProps<{ dataset: TableDataset }>();
const emit = defineEmits<{ change: [dataset: TableDataset] }>();
const config = computed(() => props.dataset.pivot);
function update(patch: Partial<PivotConfig>) { emit("change", { ...props.dataset, pivot: { ...config.value, ...patch } }); }
function toggle(axis: "rows" | "columns", id: string) {
  const current = config.value[axis]; const other = axis === "rows" ? "columns" : "rows";
  update({ [axis]: current.includes(id) ? current.filter(v => v !== id) : [...current, id], [other]: config.value[other].filter(v => v !== id) });
}
const numericFields = computed(() => props.dataset.fields.filter(f => f.type === "number"));
const output = computed(() => { try { return { data: buildPivot(props.dataset, config.value), error: "" }; } catch (e) { return { data: null, error: e instanceof Error ? e.message : "Не удалось построить сводную." }; } });
const filterOptions = computed(() => {
  const i = props.dataset.fields.findIndex(f => f.id === config.value.filterField);
  const values = new Map<string, string>();
  if (i >= 0) props.dataset.rows.forEach(row => values.set(JSON.stringify(row[i] ?? null), display(row[i])));
  return [...values].sort((a, b) => a[1].localeCompare(b[1], "ru"));
});
const label = (ids: string[]) => ids.map(id => props.dataset.fields.find(f => f.id === id)?.name).join(" / ");
function exportPivot() {
  const data = output.value.data; if (!data) return;
  downloadCsv(`${props.dataset.name} — сводная`, [
    [...(config.value.rows.length ? config.value.rows.map(id => label([id])) : ["Группа"]), ...data.columns.map(([, values]) => values.length ? values.map(display).join(" / ") : operations[config.value.operation]), "Итого"],
    ...data.rows.map(([key, values]) => [...(values.length ? values.map(display) : ["Все строки"]), ...data.columns.map(([column]) => data.cell(key, column)), data.rowTotal(key)]),
    ["Итого", ...Array(Math.max(0, config.value.rows.length - 1)).fill(""), ...data.columns.map(([key]) => data.columnTotal(key)), data.total],
  ]);
}
</script>

<template>
  <div class="pivot-workspace">
    <aside class="pivot-builder" aria-label="Настройки сводной">
      <div class="pivot-builder-title"><AppIcon name="sliders" :size="17" /><strong>Конструктор сводной</strong></div>
      <fieldset v-for="axis in (['rows', 'columns'] as const)" :key="axis" class="pivot-fieldset"><legend>{{ axis === 'rows' ? 'Строки' : 'Столбцы' }}<span class="count-badge">{{ config[axis].length }}</span></legend><p>{{ axis === 'rows' ? 'Группировать данные по' : 'Развернуть группы по горизонтали' }}</p><label v-for="field in dataset.fields" :key="field.id" class="pivot-field-option"><input type="checkbox" :checked="config[axis].includes(field.id)" @change="toggle(axis, field.id)" /><span class="field-type">{{ field.type === 'number' ? '#' : 'Aa' }}</span><span>{{ field.name }}</span></label></fieldset>
      <div class="pivot-measure"><label>Агрегация<select :value="config.operation" @change="update({ operation: ($event.target as HTMLSelectElement).value as PivotConfig['operation'] })"><option v-for="(name, key) in operations" :key="key" :value="key" :disabled="key !== 'count' && !numericFields.length">{{ name }}</option></select></label><label v-if="config.operation !== 'count'">Показатель<select :value="config.value" @change="update({ value: ($event.target as HTMLSelectElement).value })"><option value="" disabled>Выберите поле</option><option v-for="field in numericFields" :key="field.id" :value="field.id">{{ field.name }}</option></select></label></div>
      <div class="pivot-measure"><label>Фильтр<select :value="config.filterField" @change="update({ filterField: ($event.target as HTMLSelectElement).value, filterValue: '' })"><option value="">Все данные</option><option v-for="field in dataset.fields" :key="field.id" :value="field.id">{{ field.name }}</option></select></label><label v-if="config.filterField">Значение<select :value="config.filterValue" @change="update({ filterValue: ($event.target as HTMLSelectElement).value })"><option value="">Все значения</option><option v-for="[key, value] in filterOptions" :key="key" :value="key">{{ value }}</option></select></label></div>
    </aside>
    <section class="pivot-result">
      <div class="data-toolbar"><div><span class="eyebrow">СВОДНАЯ ТАБЛИЦА</span><h2>{{ operations[config.operation] }}<span v-if="config.operation !== 'count'"> · {{ label([config.value]) }}</span></h2></div><button :disabled="!output.data?.count" @click="exportPivot"><AppIcon name="download" :size="16" />Скачать CSV</button></div>
      <p v-if="output.error" class="state state-error" role="alert">{{ output.error }}</p>
      <template v-else-if="output.data">
        <div class="pivot-result-stats"><span>Строк в расчёте <strong>{{ output.data.count.toLocaleString('ru') }}</strong></span><span>Групп <strong>{{ output.data.rows.length }}</strong></span><span>Общий итог <strong>{{ formatNumber(output.data.total) }}</strong></span></div>
        <p v-if="config.operation !== 'count' && output.data.numeric < output.data.count" class="pivot-footnote">Пустые и нечисловые значения ({{ output.data.count - output.data.numeric }}) пропущены при расчёте показателя.</p>
        <div v-if="output.data.count" class="dataset-grid-scroll pivot-matrix"><table class="dataset-grid" aria-label="Сводная таблица"><thead><tr><th v-for="id in config.rows" :key="id">{{ label([id]) }}</th><th v-if="!config.rows.length">Группа</th><th v-for="[key, values] in output.data.columns" :key="key" class="numeric-cell">{{ values.length ? values.map(display).join(' / ') : operations[config.operation] }}</th><th class="numeric-cell pivot-total">Итого</th></tr></thead><tbody><tr v-for="[key, values] in output.data.rows" :key="key"><th v-for="(value, i) in values" :key="i">{{ display(value) }}</th><th v-if="!values.length">Все строки</th><td v-for="[column] in output.data.columns" :key="column" class="numeric-cell">{{ formatNumber(output.data.cell(key, column)) }}</td><td class="numeric-cell pivot-total">{{ formatNumber(output.data.rowTotal(key)) }}</td></tr></tbody><tfoot><tr><th :colspan="Math.max(1, config.rows.length)">Общий итог</th><td v-for="[key] in output.data.columns" :key="key" class="numeric-cell">{{ formatNumber(output.data.columnTotal(key)) }}</td><td class="numeric-cell">{{ formatNumber(output.data.total) }}</td></tr></tfoot></table></div>
        <div v-else class="tables-empty"><AppIcon name="grid" :size="30" /><h3>Нет данных для сводной</h3><p>Измените фильтр или добавьте строки в исходную таблицу.</p></div>
        <p class="pivot-footnote">{{ config.columns.length ? `Столбцы: ${label(config.columns)}. ` : '' }}Итоги рассчитаны по исходным строкам с учётом фильтра. Настройки сохраняются автоматически.</p>
      </template>
    </section>
  </div>
</template>
