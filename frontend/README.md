# Frontend (D3) — браузерный UI анализа изменений СПР

Vue 3 + TypeScript (strict, `vue-tsc`) + Vite 6 — стек UI по решению команды (docs v0.3). Без UI-кита, vue-router и Pinia: свой hash-router (composable) и локальное состояние экранов. UI **не** считает diff, pivot-итоги и distinct в браузере и **не** исполняет Python: всё это делает backend (D2) поверх ядра `decision_diff` (D1/D4).

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

## Структура `src/`

По зонам из docs/project-structure.md v0.3: `run-config/` (новый запуск), `editor/` (рабочая область, новая проверка), `run-monitor/` (список Run, мониторинг), `report-summary/`, `pivot/`, `drilldown/`, `checks-report/`; общие `api/` (типизированный клиент и DTO), `components/`, `composables/` (`useApi`, `usePolling`), `mock/` (только dev), `test/`.

Клиент перед первым запросом к `/api/*` один раз вызывает `GET /api/session` и только потом шлёт остальные: backend выдаёт новую анонимную сессию на каждый запрос без cookie, и параллельные первые запросы иначе разъезжались бы по разным сессиям.

## Экраны

- **Запуски** `#/runs` — список Run текущей сессии; автообновление, пока есть активные.
- **Новый запуск** `#/runs/new` — набор данных, процедура по каждому слоту (встроенная или сохранённый workspace/.py скрипт), проверки → `POST /api/configurations` → `POST /api/runs` с `Idempotency-Key` (повтор той же формы не создаёт дубль Run).
- **Run** `#/runs/{id}` — мониторинг: status/stage/substep, прогресс (при неизвестном total — неопределённый, без выдуманного %), журнал `events?after=`, код фактически исполненного snapshot по слоту. Вкладки отчёта доступны только после `COMPLETED`.
  - **Сводка** — числа из `GET /summary` этого Run, полнота checks, артефакты.
  - **Сводная** — раскладка/фильтры в URL. В `POST /pivot` отправляются `dimensions` из обеих осей, объект `filters` и `limit/offset`. Таблица строится из `items.dimensions/cnt`, drill-down использует `group_locator`. Итоги не суммируются, страницы переключаются явно. HTTP 4xx показываются как ошибки; только HTTP 501 включает совместимость с базовыми фактами D4.
  - **Проверки** — конкретный `report_id` (по умолчанию `initial_report_id`, никогда не «latest»); PASS/FAIL, приглушённый LOW, «исполнена, 0 строк» отдельно от PASS, ошибки исполнения (ERROR/TIMEOUT/INVALID_OUTPUT/…) отдельно от FAIL; K примеров APP_ID подписаны «K из CNT»; скачивание HTML.
  - **Новая проверка** — контракт/шаблон/пример из `GET /script-kinds`, редактор или загрузка `.py` → snapshot (`POST /scripts` или multipart `POST /scripts/upload`) → `POST /runs/{id}/check-runs` (исходные проверки + новая) → polling → открывается **новый** report_id. В режиме `builtin-only` backend отвечает `403 CUSTOM_EXECUTION_DISABLED` — UI показывает причину; режим сервера виден заранее.
- **Рабочая область** `#/scripts` — скрипты всех kind, просмотр кода, создание изменённой копии/нового скрипта для слота процедуры или проверки.

Для каждого экрана есть состояния loading / empty / error / not-ready (409) / нет доступа; ответы для ранее выбранного Run отбрасываются (stale), данные выводятся только как текст.

## Тесты

```bash
npm run typecheck          # tsc strict
npm test                   # Vitest + @vue/test-utils: client, router, экраны (на тестовом дубле wire-формата)
npm run e2e:mock           # Playwright Chromium, desktop + narrow, против MOCK (UI-поведение, не расчёт)

# реальная интеграция: backend на 127.0.0.1:8000 + dev-сервер UI
DD_API_TARGET=http://127.0.0.1:8000 npm run dev &
npm run e2e:real           # PLAYWRIGHT_BASE_URL по умолчанию http://127.0.0.1:5173
E2E_TRUSTED=1 npm run e2e:real   # только против backend с DD_EXECUTION_MODE=trusted-local на loopback

npm run check:openapi -- http://127.0.0.1:8000/openapi.json   # маршруты/поля клиента есть в OpenAPI
```

Первый запуск Playwright: `npx playwright install chromium`. Отчёты: `playwright-report/`, артефакты/скриншоты: `test-results/` (в .gitignore).

## Ограничения

- Текущий pivot API возвращает counts отдельных групп и пагинацию, без итогов по осям. Прочерк в таблице означает отсутствие ячейки на текущей странице. Фактическое evidence и ограничения real E2E: [UI_PIVOT_EVIDENCE.md](UI_PIVOT_EVIDENCE.md).
- Редактор — простой `<textarea>` (Tab = 4 пробела), не Monaco и не notebook.
- Пагинация списка Run — первые 50 (по умолчанию backend).
