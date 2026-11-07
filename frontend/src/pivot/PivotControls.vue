<script setup lang="ts">
import { computed, ref } from "vue";
import { PIVOT_DIMENSIONS } from "../api/types";
import type { PivotState } from "./query";

const props = defineProps<{ state: PivotState }>();
const emit = defineEmits<{ change: [state: PivotState] }>();
const fDim = ref<string>(PIVOT_DIMENSIONS[0]);
const fVal = ref("");
const used = computed(() => new Set([...props.state.rows, ...props.state.cols]));
const free = computed(() => PIVOT_DIMENSIONS.filter((d) => !used.value.has(d)));
const AXES = [
  ["rows", "Строки", "Добавить строку"],
  ["cols", "Колонки", "Добавить колонку"],
] as const;

function add(which: "rows" | "cols", e: Event) {
  const sel = e.target as HTMLSelectElement;
  const v = sel.value;
  sel.value = "";
  if (v) emit("change", { ...props.state, [which]: [...props.state[which], v] });
}
const remove = (which: "rows" | "cols", d: string) => emit("change", { ...props.state, [which]: props.state[which].filter((x) => x !== d) });
const swap = () => emit("change", { ...props.state, rows: props.state.cols, cols: props.state.rows });
const removeFilter = (dim: string) => emit("change", { ...props.state, filters: props.state.filters.filter((x) => x.dim !== dim) });
function addFilter() {
  emit("change", { ...props.state, filters: [...props.state.filters.filter((x) => x.dim !== fDim.value), { dim: fDim.value, op: "in", values: fVal.value.split("|") }] });
  fVal.value = "";
}
</script>

<template>
  <div class="pivot-controls">
    <div v-for="[which, title, addLabel] in AXES" :key="which" class="dimlist" :aria-label="title">
      <strong>{{ title }}:</strong>
      <span v-for="d in state[which]" :key="d" class="chip">
        {{ d }}
        <button type="button" :aria-label="`Убрать ${d}`" @click="remove(which, d)">×</button>
      </span>
      <select :aria-label="addLabel" value="" @change="add(which, $event)">
        <option value="">+ измерение</option>
        <option v-for="d in free" :key="d" :value="d">{{ d }}</option>
      </select>
    </div>
    <button type="button" :disabled="!state.cols.length" @click="swap">⇄ Поменять строки и колонки</button>
    <div class="dimlist" aria-label="Фильтры">
      <strong>Фильтры:</strong>
      <span v-for="f in state.filters" :key="f.dim" class="chip">
        {{ f.dim }} ∈ {{ f.values.map((v) => (v === "" ? "∅" : v)).join(" | ") }}
        <button type="button" :aria-label="`Убрать фильтр ${f.dim}`" @click="removeFilter(f.dim)">×</button>
      </span>
      <select v-model="fDim" aria-label="Измерение фильтра">
        <option v-for="d in PIVOT_DIMENSIONS" :key="d">{{ d }}</option>
      </select>
      <input v-model="fVal" aria-label="Значение фильтра" placeholder="значение (| — несколько)" />
      <button type="button" @click="addFilter">Добавить фильтр</button>
    </div>
  </div>
</template>
