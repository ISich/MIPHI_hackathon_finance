# Три разработчика — четыре зоны ответственности

**Состав:** пользователь попросил работать втроём, один участник ведёт две зоны. Павел работает непосредственно на стенде; коллеги — в локальных desktop-средах. **Предлагаемая раскладка:**

- **Павел: D2** — платформа, API, общий runner, интеграция и согласованный deployment.
- **Участник с ядром: D1 + D4** — существующий decision_diff, DuckDB/MartAPI, checks, facts и HTML. Имя пока не указано.
- **Frontend-участник: D3** — UI и Python workspace, локальный dev-server; отчёт о его среде разобран в [frontend-environment.md](frontend-environment.md).

Размещение Павла/коллег сообщено пользователем; конкретное совмещение D1+D4 — предложение, не назначение неизвестному человеку без согласования. Модульные PRD и ID D1–D4 сохраняются как четыре технические зоны, а не требование четырёх отдельных людей. Уже существует ядро `decision_diff` в ветке `core`; [учесть готовые части и текущего владельца](implementation-status.md) перед назначением задач. Не дублировать работу коллеги над DuckDB/MartAPI. Настройка стенда вторична к обязательному чистому запуску по README; deploy только по разрешению владельца. Не делить проект на «три человека пишут, четвёртый тестирует»: каждый поток отвечает за реализацию, тесты и документацию своего результата.

## D1 — Data engineer / сравнение

Результат: из JSON получить валидные vertical rows, comparison view и segments с воспроизводимыми правилами. Владеет `user-code/processing/`, `tests/data/`, схемами логических строк и module PRD 01. Не делает UI, HTTP CRUD и второй runner. Должен рано передать D4 маленький настоящий comparison/segments, а D2 — работающий этап на входном дескрипторе.

## D2 — Backend/platform / интеграция и стенд

Результат: конфиг → неблокирующий Run → вызов выбранных процедур → артефакты/события → публикация отчёта. Owner scope, persistence, единственный runner, registry datasets/scripts, health/readiness, настройка стенда. Владеет `backend/platform`, `execution`, `storage`, `deployment`. Координирует API/схемы, но не решает в одиночку семантику данных. Работает совместно с D1/D4 по портам хранилища, не переписывает их бизнес-логику.

## D3 — Frontend / UX / Python workspace

Результат: пользователь проходит весь сценарий в браузере. Конфиги, выбор источника каждого скрипта, правка и применение процедуры/check, прогресс/журнал, summary, изменяемая сводная, drill-down, checks и экспорт. Владеет `frontend/`, браузерными E2E; не реализует второй diff в JS и не пересчитывает distinct итог простым SUM.

## D4 — Analytics backend / MartAPI / checks / HTML

Результат: сравнение → facts с membership → MartAPI → пять исходных checks → summary/pivot/drill-down/HTML. Владеет `backend/reporting`, `mart`, `checks`, `exports`, `user-code/aggregation`, `user-code/checks`, `tests/reporting`. ИИ-адаптер — после решения об объёме, не вместо ядра. Не разрабатывает отдельную очередь, авторизацию и общую ФС-изоляцию.

## Почему именно так

D1 не ждёт UI, D3 начинает с согласованного API, D4 пишет MartAPI и событийные fixtures параллельно нормализации, D2 сразу запускает всё тем же production-путём. Не возникает двух команд, независимо реализующих хранение или исполнение Python. Тяжёлая часть UI не остаётся «на потом».

## Общие файлы: один steward, обязательный второй reviewer

При совмещении D1+D4 один человек не ревьюит сам себя: стык data→MartAPI/facts проверяет Павел (D2), frontend-consumer — D3. Любой указанный ниже reviewer должен быть другим человеком; если обе роли у одного, привлекается D2/D3.

- HTTP/OpenAPI/общие DTO: D2 steward; D3 reviewer, для аналитических ответов D4.
- Normalized/comparison/segments: D1 steward; D4 reviewer; физическое хранение меняет D2.
- Facts/group locator/MartAPI: D4 steward; D1 reviewer, D3 проверяет потребление.
- Run/execution/events: D2 steward; D1/D4 проверяют producer, D3 consumer.
- Сквозная приёмка: каждый владелец отвечает за свой AC; интеграционный прогон ведёт D2, браузерный — D3. Не поручать все тесты D4.

## Первые задачи для каждого, без ожидания большого PR

- **D1:** описать logical rows → событийная fixture → configurable arrays/exclusions → normalizer/comparator → segments. Первый результат — данные одной пары плюс тест, не тысячи строк неиспытанного кода.
- **D2:** согласовать descriptors → RunConfig/Run states → worker и journal → callback/ports для D1/D4 → owner scope → registry и стенд.
- **D3:** маршруты/экраны и API client → конфиг+редактор+мониторинг → реальный запуск → pivot/drill-down/checks. Контрактные UI fixtures помечаются, реальная интеграция не откладывается.
- **D4:** MartAPI на малой fixture → пять checks и события FAIL → aggregation/membership → report query/API adapter → HTML и check-only execution.

Порядок интеграции и границы готовности: [integration-plan.md](integration-plan.md). Детальные задачи: четыре [модульных PRD](README.md).
