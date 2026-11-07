<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { IS_MOCK } from "../api/instance";
import { href, navigate, useRoute } from "../router";
import AppIcon from "./AppIcon.vue";
import MockBanner from "./MockBanner.vue";

const route = useRoute();
const collapsed = ref(false);
const mobileOpen = ref(false);
const isMobile = ref(false);
const dark = ref(false);
const search = ref("");
const palette = ref<HTMLDialogElement>();
const menuButton = ref<HTMLButtonElement>();
const sidebar = ref<HTMLElement>();
const navigation = [
  { label: "Обзор", description: "Активность и показатели запусков", icon: "home", to: href("overview"), section: "overview" },
  { label: "Запуски", description: "История расчётов и отчёты", icon: "runs", to: href("runs"), section: "runs" },
  { label: "Новый запуск", description: "Выбрать данные и конфигурацию", icon: "plus", to: href("runs", "new"), section: "new" },
  { label: "Рабочая область", description: "Процедуры и Python-проверки", icon: "code", to: href("scripts"), section: "scripts" },
];
const activeSection = computed(() => route.value.parts[1] === "new" && route.value.parts[0] === "runs" ? "new" : route.value.parts[0] ?? "runs");
const title = computed(() => navigation.find(item => item.section === activeSection.value)?.label ?? "Запуски");
const commands = computed(() => navigation.filter(item => `${item.label} ${item.description}`.toLocaleLowerCase("ru").includes(search.value.toLocaleLowerCase("ru"))));
const sidebarVisible = computed(() => isMobile.value ? mobileOpen.value : !collapsed.value);

async function closeSidebar() {
  if (!mobileOpen.value) return;
  mobileOpen.value = false;
  await nextTick();
  menuButton.value?.focus();
}

function toggleSidebar() {
  if (isMobile.value) mobileOpen.value = !mobileOpen.value;
  else collapsed.value = !collapsed.value;
}

function focusContent() { document.getElementById("main-content")?.focus(); }

function openPalette() {
  search.value = "";
  if (!palette.value?.open) palette.value?.showModal();
}

function selectFirstCommand() {
  const first = commands.value[0];
  if (!first) return;
  palette.value?.close();
  navigate(first.to);
}

function toggleTheme() {
  dark.value = !dark.value;
  document.documentElement.dataset.theme = dark.value ? "dark" : "light";
  try { localStorage.setItem("spr.theme", dark.value ? "dark" : "light"); } catch {}
}

function onKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openPalette();
  }
  if (event.key === "Escape") closeSidebar();
  if (event.key !== "Tab" || !isMobile.value || !mobileOpen.value) return;
  const controls = sidebar.value?.querySelectorAll<HTMLElement>("a, button");
  const first = controls?.[0];
  const last = controls?.[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}

const mobileQuery = window.matchMedia?.("(max-width: 760px)");
function updateMobile() { isMobile.value = mobileQuery?.matches ?? false; mobileOpen.value = false; }
watch(() => route.value.path, closeSidebar);
watch(mobileOpen, async (open) => {
  if (open) {
    await nextTick();
    sidebar.value?.querySelector<HTMLElement>("a, button")?.focus();
  }
});
onMounted(() => {
  updateMobile();
  mobileQuery?.addEventListener("change", updateMobile);
  window.addEventListener("keydown", onKeydown);
  try { dark.value = localStorage.getItem("spr.theme") === "dark"; } catch {}
  document.documentElement.dataset.theme = dark.value ? "dark" : "light";
});
onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown);
  mobileQuery?.removeEventListener("change", updateMobile);
});
</script>

<template>
  <a href="#main-content" class="skip-link" @click.prevent="focusContent">К содержимому</a>
  <div class="dashboard-shell" :class="{ 'sidebar-collapsed': !sidebarVisible }">
    <button v-if="isMobile && mobileOpen" class="sidebar-backdrop" aria-label="Закрыть меню" tabindex="-1" @click="closeSidebar" />
    <aside id="app-sidebar" ref="sidebar" v-show="sidebarVisible" class="app-sidebar" :role="isMobile ? 'dialog' : undefined" :aria-modal="isMobile && mobileOpen ? true : undefined" aria-label="Навигация проекта">
      <a class="workspace-brand" :href="href('overview')">
        <span class="brand-mark"><AppIcon name="activity" :size="20" /></span>
        <span><strong>СПР Аналитика</strong><small>Анализ изменений</small></span>
        <AppIcon name="chevrons" :size="16" class="brand-chevron" />
      </a>
      <button class="sidebar-search" @click="openPalette"><AppIcon name="search" :size="17" /><span>Быстрый переход</span><kbd>⌘ K</kbd></button>
      <span class="nav-caption">Рабочее пространство</span>
      <nav class="sidebar-nav" aria-label="Основная навигация">
        <a v-for="item in navigation" :key="item.section" :href="item.to" :class="{ active: activeSection === item.section }" :aria-current="activeSection === item.section ? 'page' : undefined" @click="closeSidebar">
          <AppIcon :name="item.icon" :size="19" /><span>{{ item.label }}</span><span v-if="item.section === 'new'" class="nav-shortcut">+</span>
        </a>
      </nav>
      <div class="sidebar-note"><span class="note-icon"><AppIcon name="shield" :size="18" /></span><strong>От данных к решению</strong><p>Сравнивайте версии СПР, исследуйте изменения и проверяйте гипотезы.</p><a :href="href('runs', 'new')">Начать анализ <AppIcon name="arrow" :size="15" /></a></div>
      <div class="sidebar-bottom">
        <a href="https://github.com/ISich/MIPHI_hackathon_finance" target="_blank" rel="noopener noreferrer"><AppIcon name="book" :size="18" />Документация<AppIcon name="arrow" :size="14" /></a>
        <button @click="openPalette"><AppIcon name="help" :size="18" />Навигация и поиск<kbd>⌘ K</kbd></button>
      </div>
      <div class="session-profile"><span class="session-avatar">ЛС</span><span><strong>Локальная сессия</strong><small>{{ IS_MOCK ? 'Демонстрационный режим' : 'Рабочее пространство' }}</small></span><span class="session-dot" /></div>
    </aside>
    <div class="dashboard-main" :inert="isMobile && mobileOpen">
      <header class="dashboard-header">
        <div class="header-location"><button ref="menuButton" class="icon-button" :aria-label="sidebarVisible ? 'Скрыть боковую панель' : 'Открыть боковую панель'" :aria-expanded="sidebarVisible" aria-controls="app-sidebar" @click="toggleSidebar"><AppIcon name="panel" :size="19" /></button><span class="header-divider" /><span class="header-project">Рабочее пространство</span><span class="breadcrumb-slash">/</span><strong>{{ title }}</strong></div>
        <div class="header-actions"><span class="environment-label"><span />{{ IS_MOCK ? 'Демо' : 'СПР' }}</span><button class="icon-button" :aria-label="dark ? 'Включить светлую тему' : 'Включить тёмную тему'" :title="dark ? 'Светлая тема' : 'Тёмная тема'" @click="toggleTheme"><AppIcon :name="dark ? 'sun' : 'moon'" :size="19" /></button><a class="quick-create" :href="href('runs', 'new')" aria-label="Создать новый запуск" title="Новый запуск"><AppIcon name="plus" :size="20" /></a></div>
      </header>
      <MockBanner v-if="IS_MOCK" />
      <main id="main-content" tabindex="-1"><slot /></main>
      <footer class="workspace-footer"><span>СПР Аналитика <span class="footer-dot">·</span> Анализ изменений и контроль качества</span><span>Vue 3 <span class="footer-dot">/</span> {{ IS_MOCK ? 'MOCK · не реальные расчёты' : 'Данные текущей сессии' }}</span></footer>
    </div>
  </div>
  <dialog ref="palette" class="command-palette" aria-labelledby="palette-title" @click="event => { if (event.target === palette) palette?.close(); }">
    <form method="dialog" class="command-header"><AppIcon name="search" /><label id="palette-title" class="sr-only" for="command-search">Быстрый переход</label><input id="command-search" v-model="search" placeholder="Куда хотите перейти?" autocomplete="off" @keydown.enter.prevent="selectFirstCommand" /><button class="icon-button" aria-label="Закрыть поиск"><AppIcon name="close" :size="18" /></button></form>
    <div class="command-results"><span class="nav-caption">Страницы проекта</span><a v-for="item in commands" :key="item.section" :href="item.to" @click="palette?.close()"><AppIcon :name="item.icon" /><span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span><AppIcon name="arrow" :size="16" /></a><p v-if="!commands.length" class="muted">Ничего не найдено. Попробуйте «запуски» или «процедуры».</p></div>
    <div class="command-footer"><kbd>Tab</kbd> выбрать <kbd>Enter</kbd> перейти <kbd>Esc</kbd> закрыть</div>
  </dialog>
</template>
