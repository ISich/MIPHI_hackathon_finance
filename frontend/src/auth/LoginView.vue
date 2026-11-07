<script setup lang="ts">
import { ref } from "vue";
import { ApiError } from "../api/client";
import { api } from "../api/instance";
import type { AccountUser } from "../api/types";
import AppIcon from "../components/AppIcon.vue";

const emit = defineEmits<{ signedIn: [user: AccountUser] }>();
const username = ref("");
const password = ref("");
const showPassword = ref(false);
const pending = ref(false);
const error = ref("");

async function submit() {
  if (pending.value) return;
  error.value = "";
  pending.value = true;
  try {
    const session = await api.login(username.value.trim(), password.value);
    if (!session.authenticated || !session.user) throw new Error("Сервер не подтвердил вход. Повторите попытку.");
    password.value = "";
    emit("signedIn", session.user);
  } catch (e) {
    error.value = e instanceof ApiError && e.code === "INVALID_CREDENTIALS"
      ? "Неверный логин или пароль. Проверьте данные и попробуйте ещё раз."
      : e instanceof Error ? e.message : "Не удалось войти. Повторите попытку.";
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <div class="auth-page">
    <a class="auth-brand" href="#/runs"><span class="brand-mark"><AppIcon name="activity" :size="20" /></span>СПР Аналитика</a>
    <section class="auth-card" aria-labelledby="login-title">
        <span class="auth-symbol"><AppIcon name="shield" :size="23" /></span>
        <h1 id="login-title">Вход в систему</h1>
        <p class="muted login-subtitle">Войдите, чтобы продолжить работу с анализом изменений.</p>
        <form class="form login-form" :aria-busy="pending" @submit.prevent="submit">
          <label for="login-username">Логин
            <input id="login-username" v-model="username" name="username" type="text" autocomplete="username" autocapitalize="none" :spellcheck="false" placeholder="Введите логин" maxlength="120" required :disabled="pending" :aria-invalid="!!error" :aria-describedby="error ? 'login-error' : undefined" />
          </label>
          <label for="login-password">Пароль
            <span class="login-password-field">
              <input id="login-password" v-model="password" name="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" placeholder="Введите пароль" maxlength="256" required :disabled="pending" :aria-invalid="!!error" :aria-describedby="error ? 'login-error' : undefined" />
              <button type="button" class="login-password-toggle" :aria-label="showPassword ? 'Скрыть пароль' : 'Показать пароль'" :aria-pressed="showPassword" :disabled="pending" @click="showPassword = !showPassword">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" stroke="currentColor" stroke-width="1.6" /><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.6" /><path v-if="showPassword" d="m3 3 18 18" stroke="currentColor" stroke-width="1.6" /></svg>
              </button>
            </span>
          </label>
          <p v-if="error" id="login-error" class="login-error" role="alert">{{ error }}</p>
          <button type="submit" class="primary login-submit" :disabled="pending">{{ pending ? 'Входим…' : 'Войти' }}<span v-if="!pending" aria-hidden="true">→</span></button>
        </form>
        <p class="login-help">Нет доступа? Обратитесь к администратору.</p>
    </section>
    <p class="auth-footer">Анализ изменений СПР</p>
  </div>
</template>
