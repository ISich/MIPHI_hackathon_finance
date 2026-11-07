# Frontend (D3) — браузерный UI анализа изменений СПР

Vite 6 + React 18 + TypeScript (strict). Без UI-кита, router-библиотеки и state-менеджера. UI **не** считает diff, pivot-итоги и distinct в браузере и **не** исполняет Python: всё это делает backend (D2) поверх ядра `decision_diff` (D1/D4).

## Требования

Node 22 и npm (lockfile — `package-lock.json`; pnpm/yarn не использовать).

```bash
cd frontend
npm ci
```

## Запуск

| Режим | Команда | Что это |
|---|---|---|
| Реальный backend | `DD_API_TARGET=http://127.0.0.1:8000 npm run dev` | dev-сервер **только 127.0.0.1:5173**, `/api`, `/health`, `/ready` проксируются на backend-night |
| Mock (только разработка) | `npm run dev:mock` | синтетические данные `MOCK-…`, постоянный красный баннер «MOCK». **Не является реальным расчётом.** |
| Production build | `npm run build` → `dist/` | статические файлы; mock в сборку не попадает (подгружается динамически только в `--mode mock`) |

Backend запускается по его README (`backend/README.md` ветки feat/backend-night), например:

```bash
cd backend && .venv/bin/python -m dd_backend serve --host 127.0.0.1 --port 8000
```

Для стенда: UI и `/api` должны быть на одном origin (cookie-сессия `dd_session` HttpOnly, SameSite=Lax), а для `/runs/*` нужен SPA-fallback на `index.html` — ссылка из HTML-отчёта ведёт на `{DD_REPORT_UI_BASE}/runs/{run_id}/reports/{report_id}`, UI переписывает её в сводную этого Run.

## Экраны

- **Запуски** `#/runs` — список Run текущей сессии; автообновление, пока есть активные.
- **Новый запуск** `#/runs/new` — набор данных, процедура по каждому слоту (встроенная или сохранённый workspace/.py скрипт), проверки → `POST /api/configurations` → `POST /api/runs` с `Idempotency-Key` (повтор той же формы не создаёт дубль Run).
- **Run** `#/runs/{id}` — мониторинг: status/stage/substep, прогресс (при неизвестном total — неопределённый, без выдуманного %), журнал `events?after=`, код фактически исполненного snapshot по слоту. Вкладки отчёта доступны только после `COMPLETED`.
  - **Сводка** — числа из `GET /summary` этого Run, полнота checks, артефакты.
  - **Сводная** — раскладка/фильтры в URL, `POST /pivot` (server rollup, opaque group locators). Пока backend отвечает `501 ANALYTICS_UNAVAILABLE`, UI честно показывает причину и переходит на базовые факты D4 (`/pivot-facts`, CNT без суммирования) с drill-down `/pivot-facts/applications`.
  - **Проверки** — конкретный `report_id` (по умолчанию `initial_report_id`, никогда не «latest»); PASS/FAIL, приглушённый LOW, «исполнена, 0 строк» отдельно от PASS, ошибки исполнения (ERROR/TIMEOUT/INVALID_OUTPUT/…) отдельно от FAIL; K примеров APP_ID подписаны «K из CNT»; скачивание HTML.
  - **Новая проверка** — контракт/шаблон/пример из `GET /script-kinds`, редактор или загрузка `.py` → snapshot (`POST /scripts` или multipart `POST /scripts/upload`) → `POST /runs/{id}/check-runs` (исходные проверки + новая) → polling → открывается **новый** report_id. В режиме `builtin-only` backend отвечает `403 CUSTOM_EXECUTION_DISABLED` — UI показывает причину; режим сервера виден заранее.
- **Рабочая область** `#/scripts` — скрипты всех kind, просмотр кода, создание изменённой копии/нового скрипта для слота процедуры или проверки.

Для каждого экрана есть состояния loading / empty / error / not-ready (409) / нет доступа; ответы для ранее выбранного Run отбрасываются (stale), данные выводятся только как текст.

## Тесты

```bash
npm run typecheck          # tsc strict
npm test                   # Vitest: client, router, экраны (на тестовом дубле wire-формата)
npm run e2e:mock           # Playwright Chromium, desktop + narrow, против MOCK (UI-поведение, не расчёт)

# реальная интеграция: backend на 127.0.0.1:8000 + dev-сервер UI
DD_API_TARGET=http://127.0.0.1:8000 npm run dev &
npm run e2e:real           # PLAYWRIGHT_BASE_URL по умолчанию http://127.0.0.1:5173
E2E_TRUSTED=1 npm run e2e:real   # только против backend с DD_EXECUTION_MODE=trusted-local на loopback

npm run check:openapi -- http://127.0.0.1:8000/openapi.json   # маршруты/поля клиента есть в OpenAPI
```

Первый запуск Playwright: `npx playwright install chromium`. Отчёты: `playwright-report/`, артефакты/скриншоты: `test-results/` (в .gitignore).

## Ограничения

- Server pivot rollup / group locators / полный distinct total при drill-down зависят от D4; сейчас backend отдаёт 501 и drill-down без полного total — UI это показывает, а не подменяет.
- Редактор — простой `<textarea>` (Tab = 4 пробела), не Monaco и не notebook.
- Пагинация списка Run — первые 50 (по умолчанию backend).
