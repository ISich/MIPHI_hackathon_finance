<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { getCoreRowModel, getFilteredRowModel, getPaginationRowModel, getSortedRowModel, useVueTable, type SortingState } from "@tanstack/vue-table";
import { display, MAX_ROWS, numberValue, type TableDataset, type Value } from "./model";
import { downloadCsv } from "./files";
import AppIcon from "../components/AppIcon.vue";

const props = defineProps<{ dataset: TableDataset }>();
const emit = defineEmits<{ change: [dataset: TableDataset] }>();
const search = ref(""); const sorting = ref<SortingState>([]); const page = ref({ pageIndex: 0, pageSize: 50 });
const error = ref(""); const editing = ref(""); const draft = ref(""); const newColumn = ref(""); const columnType = ref<"text" | "number">("text");
const selection = ref(new Set<number>());
const columns = computed(() => props.dataset.fields.map((field, index) => ({ id: field.id, accessorFn: (row: Value[]) => row[index], header: field.name, enableGlobalFilter: true })));
const table = useVueTable({
  get data() { return props.dataset.rows; }, get columns() { return columns.value; },
  state: { get globalFilter() { return search.value; }, get sorting() { return sorting.value; }, get pagination() { return page.value; } },
  onSortingChange: updater => { sorting.value = typeof updater === "function" ? updater(sorting.value) : updater; },
  onPaginationChange: updater => { page.value = typeof updater === "function" ? updater(page.value) : updater; },
  globalFilterFn: (row, column, filter) => String(row.getValue(column) ?? "").toLocaleLowerCase("ru").includes(String(filter).toLocaleLowerCase("ru")),
  getCoreRowModel: getCoreRowModel(), getFilteredRowModel: getFilteredRowModel(), getSortedRowModel: getSortedRowModel(), getPaginationRowModel: getPaginationRowModel(), autoResetPageIndex: false,
});
watch(search, () => { page.value.pageIndex = 0; });
watch(() => props.dataset.id, () => { search.value = ""; page.value.pageIndex = 0; sorting.value = []; selection.value = new Set(); editing.value = ""; error.value = ""; });
function change(rows: Value[][]) { emit("change", { ...props.dataset, rows }); }
function startEdit(row: number, col: number) { editing.value = `${row}:${col}`; draft.value = String(props.dataset.rows[row]?.[col] ?? ""); error.value = ""; }
function commit(row: number, col: number) {
  if (editing.value !== `${row}:${col}`) return;
  const field = props.dataset.fields[col]!;
  const value = field.type === "number" ? numberValue(draft.value) : draft.value;
  if (field.type === "number" && draft.value.trim() && value === null) { error.value = `«${field.name}»: введите число или оставьте ячейку пустой.`; return; }
  const rows = props.dataset.rows.slice(); rows[row] = [...rows[row]!]; rows[row]![col] = value;
  editing.value = ""; error.value = ""; change(rows);
}
function select(index: number, checked: boolean) { const next = new Set(selection.value); checked ? next.add(index) : next.delete(index); selection.value = next; }
function deleteRows() { change(props.dataset.rows.filter((_, i) => !selection.value.has(i))); selection.value = new Set(); page.value.pageIndex = 0; }
function addRow() { if (props.dataset.rows.length >= MAX_ROWS) return; search.value = ""; sorting.value = []; change([...props.dataset.rows, props.dataset.fields.map(() => null)]); page.value.pageIndex = Math.floor(props.dataset.rows.length / page.value.pageSize); }
function addColumn() {
  const name = newColumn.value.trim(); if (!name) return;
  if (props.dataset.fields.some(f => f.name === name)) { error.value = "Столбец с таким именем уже существует."; return; }
  emit("change", { ...props.dataset, fields: [...props.dataset.fields, { id: crypto.randomUUID(), name, type: columnType.value }], rows: props.dataset.rows.map(row => [...row, null]) });
  newColumn.value = ""; error.value = "";
}
function exportRows() { downloadCsv(props.dataset.name, [props.dataset.fields.map(f => f.name), ...table.getSortedRowModel().rows.map(row => row.original)]); }
</script>

<template>
  <div class="data-toolbar">
    <div class="data-search"><AppIcon name="search" :size="17" /><input v-model="search" aria-label="Поиск по таблице" placeholder="Поиск по всем столбцам…" /></div>
    <div class="data-actions"><button v-if="selection.size" class="danger-text" @click="deleteRows">Удалить строки ({{ selection.size }})</button><button :disabled="dataset.rows.length >= MAX_ROWS" @click="addRow"><AppIcon name="plus" :size="16" />Строка</button><button @click="exportRows"><AppIcon name="download" :size="16" />CSV</button></div>
  </div>
  <p v-if="error" class="state state-error" role="alert">{{ error }}</p>
  <div class="dataset-grid-scroll">
    <table class="dataset-grid" aria-label="Данные таблицы">
      <thead><tr><th class="row-number">#</th><th v-for="header in table.getFlatHeaders()" :key="header.id" :aria-sort="header.column.getIsSorted() === 'asc' ? 'ascending' : header.column.getIsSorted() === 'desc' ? 'descending' : 'none'"><button @click="header.column.toggleSorting()"><span class="field-type">{{ dataset.fields.find(f => f.id === header.id)?.type === 'number' ? '#' : 'Aa' }}</span>{{ header.column.columnDef.header }}<span class="sort-hint">{{ header.column.getIsSorted() === 'asc' ? '↑' : header.column.getIsSorted() === 'desc' ? '↓' : '↕' }}</span></button></th></tr></thead>
      <tbody><tr v-for="row in table.getRowModel().rows" :key="row.id" :class="{ 'selected-row': selection.has(row.index) }"><th class="row-number"><input type="checkbox" :aria-label="`Выбрать строку ${row.index + 1}`" :checked="selection.has(row.index)" @change="select(row.index, ($event.target as HTMLInputElement).checked)" /><span>{{ row.index + 1 }}</span></th><td v-for="(cell, col) in row.getVisibleCells()" :key="cell.id" :class="{ 'numeric-cell': dataset.fields[col]?.type === 'number' }"><input v-if="editing === `${row.index}:${col}`" :ref="el => (el as HTMLInputElement | null)?.focus()" v-model="draft" :aria-label="`Значение: ${dataset.fields[col]?.name}, строка ${row.index + 1}`" @blur="commit(row.index, col)" @keydown.enter.prevent="commit(row.index, col)" @keydown.esc="editing = ''; error = ''" /><button v-else class="cell-value" :aria-label="`Изменить: ${dataset.fields[col]?.name}, строка ${row.index + 1}`" :title="String(cell.getValue() ?? '')" @click="startEdit(row.index, col)"><span :class="{ 'empty-cell': cell.getValue() == null || cell.getValue() === '' }">{{ display(cell.getValue() as Value) }}</span></button></td></tr><tr v-if="!table.getRowModel().rows.length"><td :colspan="dataset.fields.length + 1" class="grid-empty">{{ search ? 'По вашему запросу ничего не найдено.' : 'Пока нет строк. Добавьте первую строку.' }}</td></tr></tbody>
    </table>
  </div>
  <div class="dataset-pagination"><span>{{ table.getFilteredRowModel().rows.length.toLocaleString('ru') }} из {{ dataset.rows.length.toLocaleString('ru') }} строк <span class="footer-dot">·</span> Нажмите ячейку для редактирования</span><div><label>На странице <select :value="page.pageSize" @change="page = { pageIndex: 0, pageSize: Number(($event.target as HTMLSelectElement).value) }"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label><button aria-label="Предыдущая страница" :disabled="!table.getCanPreviousPage()" @click="table.previousPage()">←</button><span>{{ page.pageIndex + 1 }} / {{ Math.max(1, table.getPageCount()) }}</span><button aria-label="Следующая страница" :disabled="!table.getCanNextPage()" @click="table.nextPage()">→</button></div></div>
  <form v-if="dataset.fields.length < 200" class="add-column-form" @submit.prevent="addColumn"><AppIcon name="plus" :size="16" /><input v-model="newColumn" aria-label="Имя нового столбца" placeholder="Новый столбец" maxlength="120" /><select v-model="columnType" aria-label="Тип нового столбца"><option value="text">Текст</option><option value="number">Число</option></select><button :disabled="!newColumn.trim()">Добавить столбец</button></form>
</template>
