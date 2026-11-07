# Промпт для проверки PR #10 на Linux-стенде

Ты проверяешь и доводишь до приёмки PR https://github.com/ISich/MIPHI_hackathon_finance/pull/10
в репозитории `ISich/MIPHI_hackathon_finance`. Это продолжение PR #9, а не альтернативный UI.
Не сливай PR и не меняй рабочий стенд команды. Работай в изолированном worktree, с отдельным
`DD_HOME`, свободными loopback-портами и собственными процессами. Прочитай применимые AGENTS.md.

## Какую версию проверять

Если Артур передал TARGET_SHA, проверь именно его. Иначе однократно получи `headRefOid` PR #10
через `gh pr view 10 --repo ISich/MIPHI_hackathon_finance --json headRefOid`, выполни fetch и
создай detached worktree на этом SHA. Зафиксируй `git rev-parse HEAD` и `git status --porcelain`
в отчёте. Коммит `41df7ed` уже устарел; его результаты не подтверждают исправленный head.
Если PR продвинулся во время тестов, отдельно укажи это и не переноси результат на новый SHA.

Исправления, которые должны присутствовать:

- `1e-400` и `9007199254740990.5` не округляются при преобразовании строк: CSV сохраняет их
  текстом, редактирование числовой ячейки отказывает без изменения старого значения.
- Тесты числовой точности, импорта, редактирования, CSV-экспорта и reload.
- Смена настроенного логина отзывает старые credentials/сессии, сохраняя owner и работу
  обычного bootstrap-аккаунта. Устаревшие дополнительные аккаунты не могут войти.
- Непарные Unicode surrogate в JSON-строках возвращают 422 с envelope, а не 500.

## Окружение и зависимости

1. Нужен настоящий Linux с рабочим supervisor/worker и доступом к `/proc`, Python >=3.11,
   Node/npm, Chromium Playwright и системными зависимостями браузера. Не запускай сразу
   несколько тяжёлых наборов на загруженном VPS. Сохрани версии ОС, Python/Node, зависимости
   и load average; секреты и значения паролей не выводи.
2. Создай отдельный virtualenv в worktree и установи зависимости по backend/README.md:
   `pip install -r backend/requirements-dev.txt -e backend`. Выполни `backend/scripts/fetch_core.sh`.
   Прочитай и сверь оба CORE_COMMIT. Ядро должно быть установлено именно через VCS на этот SHA.
   `core_info()` должен вернуть этот commit в `vcs_info`, а не `null`. При отсутствии provenance
   переустанови pinned `decision-diff-core` из Git согласно requirements.txt; не подделывай
   direct_url.json, heartbeat, /ready или ожидаемый SHA ради зелёной проверки.
3. В `frontend` выполни `npm ci` и при необходимости `npx playwright install --with-deps chromium`.

## Локальные наборы на проверяемом SHA

Запускай последовательно, сохраняя stdout/stderr, exit code и JUnit/report там, где доступны.
Артефакты складывай вне исходников (или в игнорируемый `qa-runs/`). Не используй `|| true`,
которое превращает провал в успех; если используешь tee, сохрани код команды через pipefail.

- `cd frontend && npm test`
- `cd frontend && npm run build` (включает strict typecheck)
- `cd frontend && PLAYWRIGHT_MOCK_PORT=<свободный_порт> npm run e2e:mock -- --retries=0 --reporter=list`
  Здесь 4 `test.fail` в guard.meta.spec.ts намеренно проверяют детектор ошибок. Укажи их отдельно.
  Mock-сценарии не доказывают вычисления backend.
- Из корня: `python -m pytest backend/tests -vv -rA --durations=20 --junitxml=<путь>`.
  Для воспроизводимости очисти унаследованные DD_AUTH_USERNAME/PASSWORD/DISPLAY_NAME в окружении
  этого тестового процесса: тесты создают собственные временные БД и ожидают локальные defaults.
  Допустим внешний лимит 45 минут. Timeout/kill без итоговой сводки = INCOMPLETE, не PASS.
  В первую очередь нужны test_auth.py, test_dataset_tables.py, /ready и OpenAPI snapshot,
  но их успех не заменяет полный backend suite.

## Живой backend и UI

1. Подними отдельный API из этого worktree, `DD_EXECUTION_MODE=builtin-only`,
   `DD_EMBEDDED_WORKER=1`, с новым DD_HOME и loopback bind. Порты заранее проверь: нельзя
   принять ответ уже работающего постороннего сервера за проверку своего процесса.
   Используй чистое окружение auth либо отдельные согласованные тестовые credentials.
   Сохрани PID, команду без секретов и backend log. Чужие процессы не останавливай.
2. С тем же DD_HOME зарегистрируй ровно один общий dataset с именем `core fixture`,
   root `examples`, mode `files`, before `I32554354_other.json`, after `I32554354.json`
   через `python -m dd_backend register-dataset` (см. backend/README.md).
3. Проверь `/health` и `/ready` с connect/total timeout. До 60 секунд можно ждать worker.
   Требуется HTTP 200, `ready:true` и все checks `ok:true`. Сохрани полный JSON /ready.
   При 503 найди конкретные проваленные checks (core provenance, worker, пути, blocked jobs),
   их первопричину и backend traceback. Не выключай проверку готовности и не ослабляй worker.
4. Запусти UI в обычном режиме, без VITE_API_MODE=mock:
   `DD_API_TARGET=http://127.0.0.1:<api_port> npm run dev -- --port <ui_port>`.
   UI и API используют один origin через Vite proxy. Убедись, что MOCK banner отсутствует.
5. В `frontend`:
   - `npm run check:openapi -- http://127.0.0.1:<api_port>/openapi.json`
   - `PLAYWRIGHT_BASE_URL=http://127.0.0.1:<ui_port> npx playwright test --retries=0 --reporter=list`
     При нестандартном аккаунте передай E2E_USERNAME/E2E_PASSWORD через окружение, не публикуя их.
     Не указывай grep, чтобы не скрыть проблемные сценарии. Ожидаются desktop + narrow,
     включая auth, session и все real.spec.ts. Для builtin-only не ставь E2E_TRUSTED=1.
     Сохрани stdout, exit code, screenshots, traces/browser-errors при сбое и перечень всех тестов.
6. Дополнительно открой реальный скачанный HTML: общая ссылка должна вести в pivot того же Run,
   а ссылка с app_id — к той же заявке и её BEFORE/AFTER атрибутам. Проверь возврат с report context,
   в том числе через экран входа. Одной проверки наличия href в HTML недостаточно.
7. В таблицах UI импортируй CSV с колонками `Сумма;Исходное значение` и строками
   `10;1e-400`, `20;9007199254740990.5`. Текстовые значения должны пережить экспорт и reload.
   Попытки ввести их в числовую «Сумма» должны показать ошибку и сохранить 10/20.
8. Шаг «своя Python-проверка → исполнение → новый отчёт» не подтверждается ожидаемым 403
   builtin-only. Если на стенде есть отдельное разрешённое изолированное окружение trusted-local,
   проверь его отдельно с E2E_TRUSTED=1 на loopback. Иначе пометь этот шаг NOT VERIFIED.
   Не включай trusted-local на общем/публичном сервисе и не ослабляй ограничения ради демо.
9. Если согласованный датасет 2002 пар доступен, отдельно прогони его через UI и сопоставь
   summary с API/CLI на той же ревизии. Если его нет, напиши NOT VERIFIED; не подменяй его fixture.

## Если обнаружены новые сбои

Сначала воспроизведи конкретный тест изолированно с теми же входами и сохрани traceback.
Отдели дефект UI/API-кода от окружения (например, stale/missing core commit и нет живого worker).
Исправления кода делай отдельным коммитом в ветке PR #10; не меняй main и не форс-пушь.
Не делай skip/xfail, не разрешай неожиданные 4xx/5xx и не меняй ожидаемые результаты ради green.
После исправления зафиксируй новый SHA и перепроверь затронутые наборы. В итоговом отчёте
должно быть понятно, какой SHA прошёл какой прогон; старые успешные результаты не наследуются.

## Что вернуть Артуру

- Точный SHA, чистота worktree, версии, режим и подтверждение происхождения core.
- Таблица наборов: команда, SHA, pass/fail/skip/xfail, exit code, длительность, путь к логу.
- JSON /ready и объяснение каждого прежнего 503.
- Все реальные E2E с отдельными статусами desktop/narrow, без смешивания с mock.
- Регрессии чисел, смены имени и Unicode: фактические результаты и свидетельства.
- Новые коммиты/diff, нерешённые дефекты и NOT VERIFIED (HTML, trusted-local, 2002 и т.д.).
- Вердикт READY FOR REVIEW либо NEEDS FIX / INCOMPLETE. Не называй PR готовым к merge только
  по frontend unit/build или удачному ретраю. PR самостоятельно не сливай.

В конце останови только собственные временные процессы; артефакты сохрани. Не публикуй данные
заявок, пароли, cookies и содержимое серверного окружения в PR-комментариях.
