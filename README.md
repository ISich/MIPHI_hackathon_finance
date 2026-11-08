# Анализ изменений СПР — платформа (backend + UI + QA)

**Команда:** Киндер буэно  
**Задача:** анализ изменений решений СПР между двумя прогонами (BEFORE / AFTER): обработка датасета, четыре типа изменений, сводная таблица, проверки и HTML-отчёт  
**Участники:** Арсений Воронин, Артур Хримян, Васем Тауфик, Павел Лимонов

Монорепозиторий платформы поверх ядра `decision_diff` (D1/D4). Ядро (нормализатор, сравнение,
MartAPI, BaseFacts/PivotRollup, checks, HTML-отчёт) подключается как зависимость: оно ставится pip-ом
из этого же GitHub-репозитория (`ISich/MIPHI_hackathon_finance`) по закреплённому коммиту
(см. «Закрепление ядра»).

## Демо-стенд для жюри

| | |
|---|---|
| Адрес | <https://finance.corca.ru> |
| Логин | `admin` |
| Пароль | `631885ae2746511e146c5d0b2e2c92cdd4023c889c4e664a` |
| Режим исполнения | `sandboxed`: свои процедуры и проверки исполняются в песочнице (Landlock + seccomp) |

На стенде зарегистрирован датасет `core fixture` (пара BEFORE/AFTER из фикстуры ядра). После входа
можно сразу запустить по нему прогон, открыть сводку и drill-down и скачать HTML-отчёт.

| Каталог | Что это | Документация |
|---|---|---|
| `backend/` | D2: FastAPI + SQLite + воркер с supervisor-контейнментом, хранение Run, pivot/drill-down через D4 | [backend/README.md](backend/README.md), API-примеры [backend/docs/examples/](backend/docs/examples/), схема [backend/openapi.json](backend/openapi.json) |
| `frontend/` | D3: Vue 3 + TypeScript + Vite, браузерный UI | [frontend/README.md](frontend/README.md) |
| `tests/`, `scripts/`, `requirements-qa.txt`, `pytest.ini` | QA: контракты ядра, black-box HTTP, restart, selftests, полный прогон | [docs/qa/README.md](docs/qa/README.md) |
| `docs/qa/` | Матрица трассировки требований и review-заметки | [requirements-traceability.md](docs/qa/requirements-traceability.md) |

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
- доступ по Git к `ISich/MIPHI_hackathon_finance` — оттуда pip ставит ядро по коммиту из
  [`backend/requirements.txt`](backend/requirements.txt). Если репозиторий приватный, нужна настроенная
  Git-авторизация (SSH-ключ или token).

### Локальный запуск (разработка / проверка)

```bash
git clone https://github.com/ISich/MIPHI_hackathon_finance.git && cd MIPHI_hackathon_finance

# 1. backend: API + встроенный воркер на 127.0.0.1:8000
cd backend
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt -e .
scripts/fetch_core.sh                      # checks/ и examples/ ядра по закреплённому коммиту
.venv/bin/python -m dd_backend serve --host 127.0.0.1 --port 8000

# 2. UI (в другом терминале): dev-сервер 127.0.0.1:5173 с прокси /api → backend
cd frontend && npm ci && npm run dev
```

Откройте <http://127.0.0.1:5173> и войдите как `admin` / `admin12345` (локальный пароль по умолчанию).
Проверка: `curl http://127.0.0.1:8000/health` и `curl http://127.0.0.1:8000/ready`
(`/ready` дополнительно сверяет установленный коммит ядра).

Регистрация данных (фикстура ядра или полный открытый набор, положенный в разрешённый корень):

```bash
cd backend
.venv/bin/python -m dd_backend register-dataset --name "core fixture" --root examples --mode files \
    --before I32554354_other.json --after I32554354.json

DD_DATA_ROOTS=examples=...,data=/path/to/data \
.venv/bin/python -m dd_backend register-dataset --name "RUN-20260827-0001" --root data --mode dirs \
    --before RUN-20260827-0001/RESULTS/BEFORE_MASTER --after RUN-20260827-0001/RESULTS/AFTER_BETA
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
   export DD_EXECUTION_MODE=builtin-only                   # trusted-local наружу не выставлять
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

Все переменные окружения, двухпроцессный режим (API + отдельный воркер), режимы исполнения
`builtin-only` / `trusted-local` и модель безопасности описаны в [backend/README.md](backend/README.md).

## Известные ограничения

- Сводная в UI считает только ячейки текущей страницы, итогов по осям нет: см. раздел «Ограничения» в
  [frontend/README.md](frontend/README.md).
- Пользовательский Python: `sandboxed` — песочница ядра (Landlock + seccomp, без сети/exec/fork, только файлы своего
  запуска; можно публиковать), `trusted-local` — без sandbox, только на loopback. Таблица ограничений —
  [backend/README.md](backend/README.md#sandbox-restrictions-sandboxed-mode).
- UI не прошёл QA-верификацию (см. матрицу трассировки).
