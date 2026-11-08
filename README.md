# Анализ изменений СПР — платформа (backend + UI + QA)

**Команда:** Киндер буэно  
**Задача:** анализ изменений решений СПР между двумя прогонами (BEFORE / AFTER): обработка датасета, четыре типа изменений, сводная таблица, проверки и HTML-отчёт  
**Участники:** Арсений Воронин, Артур Хримян, Васем Тауфик, Павел Лимонов

## Описание решения

Веб-платформа для анализа того, как меняются решения СПР (системы принятия решений по заявкам) между
двумя прогонами одного набора заявок: BEFORE (текущая версия, `BEFORE_MASTER`) и AFTER (новая,
`AFTER_BETA`). Аналитик выбирает датасет, запускает расчёт и получает:

- **сводку**: сколько заявок различаются, у скольких сменилось итоговое решение, доли одобрений до и после;
- **четыре типа изменений** по каждому атрибуту: `SAME`, `VALUE_CHANGED`, `ATTRIBUTE_NEW`, `ATTRIBUTE_LOST`;
- **сводную таблицу** по любым измерениям (продукт, тип партнёра, модель PD, причина отказа и т. д.)
  с подсчётом уникальных заявок и drill-down «ячейка → список заявок → атрибут до/после»;
- **проверки**: пять проверок организаторов плюс свои, написанные прямо в UI на Python;
- **HTML-отчёт** по проверкам со ссылкой обратно в UI и, по желанию, **альтернативное мнение ИИ** по отчёту.

Каждый запуск (Run) воспроизводим: при приёме фиксируются ревизия данных, код и параметры всех процедур,
коммит ядра. Этапы и журнал видны в UI в реальном времени. Свой код исполняется в отдельном процессе
под supervisor, на стенде — в песочнице.

Расчётное ядро `decision_diff` (D1/D4: нормализатор, сравнение, MartAPI, BaseFacts/PivotRollup,
checks, HTML-отчёт) лежит в ветке `core` этого же репозитория и ставится pip-ом по закреплённому
коммиту (см. «Закрепление ядра»). В `main` — платформа: backend (D2), UI (D3) и QA.

## Демо-стенд для жюри

| | |
|---|---|
| Адрес | <https://finance.corca.ru> |
| Логин | `admin` |
| Пароль | `631885ae2746511e146c5d0b2e2c92cdd4023c889c4e664a` |
| Режим исполнения | `sandboxed`: свой Python-код (процедуры и проверки) исполняется в песочнице Landlock + seccomp |
| ИИ-мнение | включено: модель `anthropic/claude-sonnet-5.5` через OpenRouter |

На стенде зарегистрированы два датасета:

- `RUN-20260827-0001` — полный открытый набор организаторов, 2002 пары заявок (расчёт ≈ 30 с);
- `core fixture 421da26` — одна пара из фикстуры ядра для быстрой проверки (≈ 5 с).

После входа можно сразу:

- запустить по любому из них прогон, открыть сводку, сводную и drill-down и скачать HTML-отчёт;
- запустить проверки, в отчёте проверок нажать «Получить мнение ИИ» (блок «Альтернативное мнение ИИ»).
  Мнение модели не меняет результаты проверок;
- в «Рабочей области» создать свой скрипт процедуры или проверки и запустить его в песочнице.

## Структура репозитория

| Каталог | Что это | Документация |
|---|---|---|
| `backend/` | D2: FastAPI + SQLite + воркер с supervisor-контейнментом, хранение Run, pivot/drill-down через D4 | [backend/README.md](backend/README.md), API-примеры [backend/docs/examples/](backend/docs/examples/), схема [backend/openapi.json](backend/openapi.json) |
| `frontend/` | D3: Vue 3 + TypeScript + Vite, браузерный UI | [frontend/README.md](frontend/README.md) |
| `tests/`, `scripts/`, `requirements-qa.txt`, `pytest.ini` | QA: контракты ядра, black-box HTTP, restart, selftests, полный прогон | [docs/qa/README.md](docs/qa/README.md) |
| `docs/qa/` | Матрица трассировки требований и review-заметки | [requirements-traceability.md](docs/qa/requirements-traceability.md) |

## Технологии

| Часть | Стек |
|---|---|
| Ядро `decision_diff` | Python 3.12, DuckDB (MartAPI для проверок), CSV-артефакты |
| Backend | FastAPI, Pydantic 2, Uvicorn, SQLite (WAL) для Run/журнала/учётных записей; воркер на subprocess + supervisor; песочница Landlock + seccomp |
| UI | Vue 3, TypeScript (strict, `vue-tsc`), Vite 6; без UI-кита и Pinia |
| Тесты | pytest (backend, QA), Vitest и Playwright (UI) |
| ИИ-мнение | OpenAI-совместимый API через OpenRouter, на стенде `anthropic/claude-sonnet-5.5` |
| Стенд | Docker, nginx (UI + прокси `/api` на одном origin), Caddy (TLS) |

## Данные

- **Источник:** открытый набор организаторов `RUN-20260827-0001`: каталоги `RESULTS/BEFORE_MASTER` и
  `RESULTS/AFTER_BETA`, по одному JSON-ответу СПР на заявку, 2002 пары (4004 файла). В репозиторий набор
  не входит; для тестов используется фикстура ядра (`examples/` ветки `core`).
- **Регистрация:** датасет — это пара каталогов (`--mode dirs`) или пара файлов (`--mode files`) внутри
  разрешённого корня `DD_DATA_ROOTS`. Пары собираются по `APP_ID`; пропущенные и битые файлы видны
  в ревизии датасета (`missing_before` / `missing_after`). Ревизия фиксирует отпечаток sha256 прочитанных
  файлов, и Run привязан к ней.
- **Нормализация:** JSON разворачивается в вертикальные строки `APP_ID, SOURCE, PATH, ARRAY_KEY, VALUE…`.
  Пресет `real` (по умолчанию) задаёт ключи массивов, чтобы элементы сравнивались по смыслу, а не по
  позиции: офферы — по `product_id + type`, продукты — по `product_id`, правила — по `name`,
  скоринговые модели — по `modelName`, каталог и тарифы — по `mfo_id + product_id`.
- **Исключения:** не сравниваются технические поля `appData.createDateTime` и `appData.request_id`.
  Список исключений и правила массивов можно переопределить в параметрах процедуры нормализации
  (`excluded_paths`, `arrays`) прямо в UI.

## Архитектура и подход

```
UI (Vue) ──/api──▶ FastAPI ──SQLite──▶ очередь задач ──▶ воркер ──subprocess──▶ ядро decision_diff
                                                         │  supervisor: лимиты памяти/времени,
                                                         │  песочница для своего кода
                                                         ▼
                              артефакты Run: normalized_union, comparison, segments, pivot_facts, mart.duckdb, HTML
```

- **Этапы Run:** `VALIDATING → NORMALIZING → COMPARING → AGGREGATING → CHECKING → FINALIZING`.
  Каждый этап — заменяемая процедура (встроенная из ядра или своя), прогресс и события пишутся в журнал.
- **Сравнение:** нормализованные срезы BEFORE и AFTER соединяются по `APP_ID + PATH + ARRAY_KEY`. Каждая пара
  атрибутов получает ровно один тип: `SAME`, `VALUE_CHANGED`, `ATTRIBUTE_NEW`, `ATTRIBUTE_LOST`.
  Заявка «с различиями» — та, у которой есть хотя бы один не-`SAME` атрибут.
- **Сводная:** на этапе `AGGREGATING` строятся `BaseFacts` (базовые группы) и принадлежность заявок к ним.
  Запрос сводной сворачивает их по выбранным осям, а итог ячейки считается как число **уникальных**
  заявок, а не строк. Ячейка отдаёт непрозрачный locator для drill-down.
- **Воспроизводимость:** при приёме Run фиксируются ревизия данных, снимки кода и параметров всех процедур
  и коммит ядра. Изменение скрипта влияет только на новые запуски. `/ready` сверяет установленный коммит
  ядра, а Run с другим ядром не исполняется (`CORE_VERSION_MISMATCH`).
- **Изоляция:** одновременно исполняется одна задача; дочерний процесс под supervisor с лимитами памяти
  (`DD_MAX_MEMORY_MB`) и времени (`DD_RUN_TIMEOUT_SECONDS`, `DD_CHECK_TIMEOUT_SECONDS`).
  Режимы исполнения своего кода: `builtin-only` (только встроенные процедуры, по умолчанию), `sandboxed`
  (песочница Landlock + seccomp: без сети, exec и fork, доступ только к файлам своего запуска — режим стенда),
  `trusted-local` (без песочницы, только на loopback).
- **Владение:** Run и скрипты принадлежат учётной записи; чужой Run отдаёт 404.

Подробнее — [docs/architecture.md](docs/architecture.md) и [backend/README.md](backend/README.md).

## Эксперименты и результаты

Полный открытый набор `RUN-20260827-0001` прогнан на стенде (Run `run_7c4a98e57e7faf805ab8`) и
независимо через CLI ядра.

| Показатель | Значение |
|---|---|
| Пары / файлы | 2002 / 4004, пропущенных и битых нет |
| **Заявок с различиями** | **502** из 2002 |
| **Заявок со сменой решения** | **385**: 273 APPROVE→REJECT, 112 REJECT→APPROVE |
| Одобрения | 657 → 496 заявок (32,8 % → 24,8 %) |
| Типы изменений, записей | SAME 275 121 · VALUE_CHANGED 7 567 · ATTRIBUTE_NEW 3 835 · ATTRIBUTE_LOST 3 010 |
| Объём артефактов, строк | normalized_union 572 221 · comparison 289 533 · pivot_facts 44 524 · segments 2002 |
| Проверки организаторов | 5 / 5 `SUCCEEDED` |
| Время accept → COMPLETED | 31 с на стенде (pipeline 27,8 с); ≈ 55 с на 8 CPU в локальном замере |

**Сверка:** summary из API совпадает с независимым прогоном CLI ядра, sha256 артефактов `comparison`,
`normalized_union`, `pivot_facts` и `segments` совпадают
([docs/quality/core-verification.md](docs/quality/core-verification.md)). Смены решения отдельно
пересчитаны напрямую из `decisionResult.decision` всех 4004 JSON. Эталона организаторов у нас нет,
поэтому сверяли с независимым расчётом.

**Тесты:** backend — 163 passed (реальное ядро и реальный subprocess-воркер), UI — `vue-tsc` без ошибок
и 113 unit-тестов Vitest. QA-наборы и матрица трассировки — [docs/qa/](docs/qa/README.md).

## Проектная документация

Исходные требования и контракты (зафиксированы до реализации; при расхождении с кодом приоритет у кода и README модулей):

- [Навигация по docs](docs/README.md)
- [Базовый PRD 0.3](docs/PRD.md)
- [Разделение ролей](docs/team.md)
- [Архитектура и границы каталогов](docs/architecture.md)
- [Контракты API](docs/contracts/api.md), [данных](docs/contracts/data.md), [исполнения](docs/contracts/execution.md)
- [План интеграции](docs/integration-plan.md) и [приёмка](docs/quality/acceptance.md)
- [Существующее ядро и стыки интеграции](docs/implementation-status.md)
- [Вопросы](docs/questions.md) и [реестр решений](docs/decisions.md)

## Закрепление ядра

Ядро закреплено на `421da26caf030ce230778ffbd07ee1f72bf71217` в трёх местах, которые должны совпадать:
[`CORE_COMMIT`](CORE_COMMIT) + [`requirements-qa.txt`](requirements-qa.txt) (QA; проверяется
`tests/contracts/test_core_pin.py`) и [`backend/CORE_COMMIT`](backend/CORE_COMMIT) +
[`backend/requirements.txt`](backend/requirements.txt) (backend; `/ready` сверяет установленный коммит).

## Как развернуть проект

### Требования

- Linux (воркер расчётов использует Linux-механизмы изоляции процессов; на macOS работает только API/UI);
- Python ≥ 3.11, Node.js 22 + npm, git;
- доступ в интернет к GitHub: pip ставит ядро из публичного репозитория `ISich/MIPHI_hackathon_finance`
  по коммиту из [`backend/requirements.txt`](backend/requirements.txt), авторизация не нужна.

### Локальный запуск (разработка / проверка)

```bash
git clone https://github.com/ISich/MIPHI_hackathon_finance.git && cd MIPHI_hackathon_finance

# 1. backend: API + встроенный воркер на 127.0.0.1:8000
cd backend
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt -e .
scripts/fetch_core.sh                      # checks/ и examples/ ядра по закреплённому коммиту
.venv/bin/python -m dd_backend serve --host 127.0.0.1 --port 8000

# 2. UI (в другом терминале, из корня клона): dev-сервер 127.0.0.1:5173 с прокси /api → backend
cd MIPHI_hackathon_finance/frontend && npm ci && npm run dev
```

Откройте <http://127.0.0.1:5173> и войдите как `admin` / `admin12345` (локальный пароль по умолчанию).
Проверка: `curl http://127.0.0.1:8000/health` и `curl http://127.0.0.1:8000/ready`
(`/ready` дополнительно сверяет установленный коммит ядра).

Регистрация данных. Фикстура ядра доступна сразу (корень `examples` разрешён по умолчанию):

```bash
cd backend
.venv/bin/python -m dd_backend register-dataset --name "core fixture" --root examples --mode files \
    --before I32554354_other.json --after I32554354.json
```

Полный открытый набор: распакуйте его, например, в `/path/to/data/RUN-20260827-0001/` и задайте корень
`data`. **Одна и та же `DD_DATA_ROOTS` нужна и для `register-dataset`, и для `serve`**: сервер читает файлы
только из корней, известных ему при старте, поэтому `serve` надо перезапустить с этой переменной.
Если переопределяете `DD_DATA_ROOTS`, перечислите и `examples`, иначе фикстура станет недоступна;
путь к нему печатает `scripts/fetch_core.sh` (`backend/.core/<sha>/examples`).

```bash
cd backend
export DD_DATA_ROOTS="examples=$PWD/.core/$(cat CORE_COMMIT)/examples,data=/path/to/data"
.venv/bin/python -m dd_backend register-dataset --name "RUN-20260827-0001" --root data --mode dirs \
    --before RUN-20260827-0001/RESULTS/BEFORE_MASTER --after RUN-20260827-0001/RESULTS/AFTER_BETA
.venv/bin/python -m dd_backend serve --host 127.0.0.1 --port 8000   # в том же окружении
```

### Развёртывание на сервере (как на стенде)

Стенд собран так: UI и API отдаются **с одного origin** — nginx раздаёт собранный UI и проксирует
API в backend (CORS не поддерживается намеренно).

1. **Backend** (Python 3.12, отдельный непривилегированный пользователь):

   ```bash
   cd backend
   python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt -e .
   scripts/fetch_core.sh
   export DD_ALLOWED_HOSTS=finance.example.org,localhost   # публичное имя сервера
   export DD_AUTH_USERNAME=admin
   export DD_AUTH_PASSWORD='<свой длинный пароль>'         # обязателен для не-loopback хоста
   export DD_EXECUTION_MODE=sandboxed                      # как на стенде; builtin-only — без своего кода;
                                                           # trusted-local наружу не выставлять
   export DD_COOKIE_SECURE=1                               # если снаружи HTTPS
   export DD_HOME=/var/lib/finance                         # SQLite и артефакты прогонов
   export DD_DATA_ROOTS=data=/data                         # каталоги, откуда можно брать датасеты
   export DD_REPORT_UI_BASE=https://finance.example.org    # ссылки в HTML-отчёте
   .venv/bin/python -m dd_backend serve --host 0.0.0.0 --port 8000 --allow-non-loopback
   ```

   Удобно оформить как systemd-unit или контейнер (`python:3.12-slim`); процесс должен переживать
   перезапуск — незавершённая задача помечается `RUN_INTERRUPTED`, очередь сохраняется.

2. **UI**: `cd frontend && npm ci && npm run build` → статические файлы в `frontend/dist/`.

3. **nginx** (TLS можно завершать в nginx или во внешнем прокси, например Caddy):

   ```nginx
   server {
     listen 80;
     server_name finance.example.org;
     root /srv/finance/dist;                       # содержимое frontend/dist
     location / { try_files $uri $uri/ /index.html; }
     location ~ ^/(api(?:/|$)|health$|ready$|openapi.json$) {
       proxy_pass http://127.0.0.1:8000;
       proxy_set_header Host $host;                # обязательно: backend сверяет Origin с Host
       proxy_set_header X-Forwarded-Proto https;
       proxy_read_timeout 120s;
     }
   }
   ```

4. Зарегистрируйте датасет командой `register-dataset` (см. выше) и проверьте
   `https://<имя>/ready` и вход в UI.

ИИ-мнение включается переменными `DD_AI_MODEL` и `DD_AI_API_KEY` (без них в отчёте статус `DISABLED`).
Все переменные окружения, двухпроцессный режим (API + отдельный воркер), режимы исполнения
`builtin-only` / `sandboxed` / `trusted-local` и модель безопасности описаны в
[backend/README.md](backend/README.md).

## Известные ограничения

- Сводная в UI считает только ячейки текущей страницы, итогов по осям нет: см. раздел «Ограничения» в
  [frontend/README.md](frontend/README.md).
- Пользовательский Python: `sandboxed` — песочница ядра (Landlock + seccomp, без сети/exec/fork, только файлы своего
  запуска; можно публиковать), `trusted-local` — без sandbox, только на loopback. Таблица ограничений —
  [backend/README.md](backend/README.md#sandbox-restrictions-sandboxed-mode).
- UI: `vue-tsc` и unit-тесты зелёные. E2E на реальном backend (`npm run e2e:real`) — 7/7 против стенда на `5ae29d7`;
  сценарий демо на полном наборе пройден в браузере. Матрица трассировки для UI не обновлялась.
