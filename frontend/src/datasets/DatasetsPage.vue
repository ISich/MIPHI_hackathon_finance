<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, IS_MOCK } from "../api/instance";
import type { Dataset } from "../api/types";
import AppIcon from "../components/AppIcon.vue";
import DataGrid from "./DataGrid.vue";
import DatasetPivot from "./DatasetPivot.vue";
import { demoDataset, readTableFile, type ImportedSheet } from "./files";
import { fromMatrix, type TableDataset } from "./model";
import { loadDatasets, removeDataset, saveDataset } from "./storage";
import "./datasets.css";

const props = defineProps<{ owner: string }>();
const tables = ref<TableDataset[]>([]); const selectedId = ref(""); const tab = ref<"data" | "pivot">("data");
const selected = computed(() => tables.value.find(t => t.id === selectedId.value));
const loading = ref(true); const busy = ref(false); const error = ref(""); const serverError = ref(""); const saved = ref("");
const serverDatasets = ref<Dataset[]>([]); const serverId = ref(""); const side = ref<"before" | "after">("after");
const importDialog = ref<HTMLDialogElement>(); const fileInput = ref<HTMLInputElement>();
const sheets = ref<ImportedSheet[]>([]); const sheetIndex = ref(0); const importName = ref(""); const importError = ref(""); const fileName = ref("");
const deleting = ref(false); const tableSearch = ref("");
const visibleTables = computed(() => tables.value.filter(t => t.name.toLocaleLowerCase("ru").includes(tableSearch.value.toLocaleLowerCase("ru"))));
const preview = computed(() => { try { const sheet = sheets.value[sheetIndex.value]; return sheet ? fromMatrix(importName.value, sheet.matrix.slice(0, 6), fileName.value) : null; } catch { return null; } });
let saveQueue: Promise<void> = Promise.resolve(); let generation = 0;

async function refreshServer() {
  serverError.value = "";
  try { serverDatasets.value = await api.datasets(); serverId.value ||= serverDatasets.value[0]?.dataset_id ?? ""; }
  catch (e) { serverError.value = message(e); }
}
onMounted(async () => {
  await Promise.allSettled([refreshServer(), (async () => {
    try { tables.value = await loadDatasets(props.owner); selectedId.value = tables.value[0]?.id ?? ""; }
    catch (e) { error.value = message(e); }
    finally { loading.value = false; }
  })()]);
});
function message(e: unknown) { return e instanceof Error ? e.message : "Не удалось выполнить действие. Попробуйте ещё раз."; }
function choose(id: string) { selectedId.value = id; deleting.value = false; }
function update(dataset: TableDataset) {
  const value = { ...dataset, updatedAt: new Date().toISOString() };
  tables.value = tables.value.map(t => t.id === value.id ? value : t);
  const current = ++generation; saved.value = "Сохраняем…";
  // Serialize writes so older snapshots can never overwrite newer edits.
  saveQueue = saveQueue.catch(() => {}).then(() => saveDataset(props.owner, value));
  void saveQueue.then(() => { if (current === generation) saved.value = "Все изменения сохранены"; }, e => { saved.value = "Не сохранено"; error.value = message(e); });
}
async function add(dataset: TableDataset) {
  await saveDataset(props.owner, dataset);
  tables.value = [dataset, ...tables.value]; choose(dataset.id); tab.value = "data"; saved.value = "Все изменения сохранены";
}
async function createDemo() { error.value = ""; try { await add(demoDataset()); } catch (e) { error.value = message(e); } }
async function createEmpty() { error.value = ""; try { const dataset = fromMatrix("Новая таблица", [["Категория", "Значение"]], "Создано вручную"); dataset.fields[1]!.type = "number"; dataset.pivot.value = "c1"; dataset.pivot.operation = "sum"; await add(dataset); } catch (e) { error.value = message(e); } }
async function deleteTable() {
  const id = selectedId.value; if (!id) return;
  try { await saveQueue.catch(() => {}); await removeDataset(props.owner, id); tables.value = tables.value.filter(t => t.id !== id); choose(tables.value[0]?.id ?? ""); }
  catch (e) { error.value = message(e); }
}
function openImport() { sheets.value = []; importError.value = ""; fileName.value = ""; importName.value = ""; sheetIndex.value = 0; if (fileInput.value) fileInput.value.value = ""; importDialog.value?.showModal(); }
async function readFile(file: File | undefined) {
  if (!file || busy.value) return;
  busy.value = true; importError.value = ""; sheets.value = [];
  try { sheets.value = await readTableFile(file); fileName.value = file.name; sheetIndex.value = 0; importName.value = file.name.replace(/\.[^.]+$/, ""); }
  catch (e) { importError.value = message(e); }
  finally { busy.value = false; }
}
async function importFile() {
  const sheet = sheets.value[sheetIndex.value]; if (!sheet || !importName.value.trim()) return;
  busy.value = true; importError.value = "";
  try { await add(fromMatrix(importName.value.trim(), sheet.matrix, `${fileName.value}${sheets.value.length > 1 ? ` · ${sheet.name}` : ''}`)); importDialog.value?.close(); }
  catch (e) { importError.value = message(e); }
  finally { busy.value = false; }
}
async function openServer() {
  const dataset = serverDatasets.value.find(d => d.dataset_id === serverId.value); if (!dataset) return;
  const sourceSide = side.value;
  busy.value = true; serverError.value = "";
  try { const result = await api.datasetTable(dataset.dataset_id, sourceSide); await add(fromMatrix(`${dataset.name} · ${sourceSide.toUpperCase()}`, [result.columns, ...result.rows], `${IS_MOCK ? 'MOCK · синтетические данные' : 'Backend'} · ${sourceSide.toUpperCase()} · ${dataset.dataset_id}`)); }
  catch (e) { serverError.value = message(e); }
  finally { busy.value = false; }
}
</script>

<template>
  <div class="datasets-page">
    <div class="page-heading"><div><span class="eyebrow">ДАННЫЕ И АНАЛИТИКА</span><h1>Таблицы и сводные</h1><p>Исследуйте данные, редактируйте таблицы и находите закономерности.</p></div><div class="data-actions"><button @click="createEmpty"><AppIcon name="plus" :size="17" />Создать таблицу</button><button class="primary" @click="openImport"><AppIcon name="upload" :size="17" />Импорт данных</button></div></div>
    <p v-if="error" class="state state-error" role="alert">{{ error }} <button @click="error = ''">Закрыть</button></p>
    <div class="tables-layout">
      <aside class="tables-library" aria-label="Библиотека таблиц">
        <div class="tables-library-heading"><strong>Мои таблицы</strong><span class="count-badge">{{ tables.length }}</span></div>
        <div v-if="tables.length" class="data-search library-search"><AppIcon name="search" :size="15" /><input v-model="tableSearch" aria-label="Найти таблицу" placeholder="Найти таблицу…" /></div>
        <div class="tables-list"><p v-if="loading" role="status">Загружаем таблицы…</p><p v-else-if="!tables.length" class="library-hint">Добавьте файл или создайте таблицу с нуля.</p><p v-else-if="!visibleTables.length" class="library-hint">Таблицы не найдены.</p><button v-for="table in visibleTables" :key="table.id" :class="{ active: selectedId === table.id }" :aria-pressed="selectedId === table.id" @click="choose(table.id)"><span class="table-list-icon"><AppIcon name="table" :size="17" /></span><span><strong>{{ table.name }}</strong><small>{{ table.rows.length.toLocaleString('ru') }} строк · {{ table.fields.length }} столбцов</small></span></button></div>
        <div class="backend-import"><span class="eyebrow">ИЗ BACKEND</span><h3>Наборы данных СПР</h3><p>Откройте BEFORE или AFTER в виде редактируемой копии.</p><label>Набор данных<select v-model="serverId" :disabled="!serverDatasets.length"><option v-if="!serverDatasets.length" value="">Нет наборов данных</option><option v-for="dataset in serverDatasets" :key="dataset.dataset_id" :value="dataset.dataset_id">{{ dataset.name }}</option></select></label><label>Версия<select v-model="side"><option value="after">AFTER · после изменений</option><option value="before">BEFORE · до изменений</option></select></label><button :disabled="!serverId || busy" @click="openServer"><AppIcon name="download" :size="16" />{{ busy ? 'Загружаем…' : 'Открыть как таблицу' }}</button><div v-if="serverError" class="backend-error" role="alert">{{ serverError }}<button @click="refreshServer">Повторить</button></div><button v-else class="text-button" @click="refreshServer">Обновить список</button></div>
        <div class="tables-local-note"><AppIcon name="database" :size="16" /><span>Таблицы и сводные сохраняются в этом браузере для вашего аккаунта.</span></div>
      </aside>
      <section v-if="selected" class="table-workspace" aria-label="Рабочая область таблицы">
        <div class="table-workspace-header"><div class="table-title"><span class="table-title-icon"><AppIcon name="table" :size="22" /></span><div><input :key="selected.id" :value="selected.name" aria-label="Название таблицы" maxlength="120" @change="update({ ...selected, name: ($event.target as HTMLInputElement).value.trim() || selected.name })" /><p :title="selected.source">{{ selected.source }}</p></div></div><button class="icon-button danger-text" aria-label="Удалить таблицу" title="Удалить таблицу" @click="deleting = !deleting"><AppIcon name="trash" :size="17" /></button></div>
        <div v-if="deleting" class="table-delete-confirm" role="alert"><span>Удалить «{{ selected.name }}» и её сводную из браузера?</span><button class="danger-text" @click="deleteTable">Удалить</button><button @click="deleting = false">Отмена</button></div>
        <div class="table-workspace-tabs"><div role="tablist" aria-label="Вид таблицы"><button id="dataset-data-tab" role="tab" :aria-selected="tab === 'data'" aria-controls="dataset-panel" :class="{ active: tab === 'data' }" @click="tab = 'data'"><AppIcon name="table" :size="16" />Данные<span class="count-badge">{{ selected.rows.length.toLocaleString('ru') }}</span></button><button id="dataset-pivot-tab" role="tab" :aria-selected="tab === 'pivot'" aria-controls="dataset-panel" :class="{ active: tab === 'pivot' }" @click="tab = 'pivot'"><AppIcon name="grid" :size="16" />Сводная таблица</button></div><span class="table-save-status" role="status"><AppIcon name="check" :size="14" />{{ saved || 'Сохранено в браузере' }}</span></div>
        <div id="dataset-panel" role="tabpanel" :aria-labelledby="tab === 'data' ? 'dataset-data-tab' : 'dataset-pivot-tab'"><DataGrid v-if="tab === 'data'" :dataset="selected" @change="update" /><DatasetPivot v-else :dataset="selected" @change="update" /></div>
      </section>
      <section v-else class="table-workspace tables-welcome"><span class="welcome-grid-icon"><AppIcon name="table" :size="38" /></span><span class="eyebrow">ВАШЕ ПРОСТРАНСТВО ДЛЯ ДАННЫХ</span><h2>От таблицы к выводам</h2><p>Загрузите CSV или Excel, откройте dataset из backend<br />и соберите сводную за несколько кликов.</p><button class="primary" @click="openImport"><AppIcon name="upload" :size="17" />Загрузить первую таблицу</button><button class="text-button" @click="createDemo">Попробовать на примере <AppIcon name="arrow" :size="15" /></button><div class="table-welcome-features"><span><AppIcon name="table" :size="17" />Редактирование ячеек</span><span><AppIcon name="sliders" :size="17" />Группировки и фильтры</span><span><AppIcon name="download" :size="17" />Экспорт в CSV</span></div></section>
    </div>
    <dialog ref="importDialog" class="table-import-dialog" aria-labelledby="table-import-title" @cancel="!busy && importDialog?.close()" @click="event => { if (event.target === importDialog && !busy) importDialog?.close(); }">
      <div class="table-import-heading"><div><span class="eyebrow">НОВЫЙ НАБОР ДАННЫХ</span><h2 id="table-import-title">Импорт таблицы</h2></div><button class="icon-button" aria-label="Закрыть импорт" :disabled="busy" @click="importDialog?.close()"><AppIcon name="close" :size="19" /></button></div>
      <div class="table-dropzone" @dragover.prevent @drop.prevent="readFile($event.dataTransfer?.files[0])"><AppIcon name="upload" :size="28" /><strong>{{ busy ? 'Читаем данные…' : fileName || 'Перетащите файл сюда' }}</strong><span>CSV, TSV или Excel (.xlsx) · до 10 МБ</span><button :disabled="busy" @click="fileInput?.click()">Выбрать файл</button><input ref="fileInput" type="file" accept=".csv,.tsv,.xlsx" class="sr-only" aria-label="Файл таблицы" :disabled="busy" @change="readFile(($event.target as HTMLInputElement).files?.[0])" /></div>
      <p v-if="importError" class="state state-error" role="alert">{{ importError }}</p>
      <div v-if="sheets.length" class="import-options"><label>Название таблицы<input v-model="importName" maxlength="120" /></label><label v-if="sheets.length > 1">Лист Excel<select v-model="sheetIndex"><option v-for="(sheet, index) in sheets" :key="index" :value="index">{{ sheet.name }}</option></select></label><p>Первая строка — заголовки. {{ Math.max(0, (sheets[sheetIndex]?.matrix.length ?? 1) - 1).toLocaleString('ru') }} строк данных.</p><div v-if="preview" class="dataset-grid-scroll import-preview"><table class="dataset-grid" aria-label="Предпросмотр импорта"><thead><tr><th v-for="field in preview.fields" :key="field.id">{{ field.name }}</th></tr></thead><tbody><tr v-for="(row, index) in preview.rows" :key="index"><td v-for="(value, col) in row" :key="col">{{ value ?? '—' }}</td></tr></tbody></table></div></div>
      <div class="table-import-footer"><span>До 20 000 строк и 200 столбцов</span><button class="primary" :disabled="!sheets.length || !importName.trim() || busy" @click="importFile">Импортировать <AppIcon name="arrow" :size="16" /></button></div>
    </dialog>
  </div>
</template>
