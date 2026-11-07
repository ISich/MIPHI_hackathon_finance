# Анализ изменений СПР — платформа (backend + UI + QA)

Монорепозиторий платформы поверх ядра `decision_diff` (D1/D4). Само ядро (нормализатор, сравнение,
MartAPI, BaseFacts/PivotRollup, checks, HTML-отчёт) здесь **не** лежит: оно ставится pip-ом из ветки
`SomeShit` этого же GitHub-репозитория (`ISich/MIPHI_hackathon_finance`) по закреплённому коммиту.

| Каталог | Что это | Документация |
|---|---|---|
| `backend/` | D2: FastAPI + SQLite + воркер с supervisor-контейнментом, хранение Run, pivot/drill-down через D4 | [backend/README.md](backend/README.md), API-примеры [backend/docs/examples/](backend/docs/examples/), схема [backend/openapi.json](backend/openapi.json) |
| `frontend/` | D3: Vue 3 + TypeScript + Vite, браузерный UI | [frontend/README.md](frontend/README.md) |
| `tests/`, `scripts/`, `requirements-qa.txt`, `pytest.ini` | QA: контракты ядра, black-box HTTP, restart, selftests, полный прогон | [docs/qa/README.md](docs/qa/README.md) |
| `docs/qa/` | Матрица трассировки требований и review-заметки | [requirements-traceability.md](docs/qa/requirements-traceability.md) |

## Закрепление ядра

Ядро закреплено на `421da26caf030ce230778ffbd07ee1f72bf71217` в трёх местах, которые должны совпадать:
[`CORE_COMMIT`](CORE_COMMIT) + [`requirements-qa.txt`](requirements-qa.txt) (QA; проверяется
`tests/contracts/test_core_pin.py`) и [`backend/CORE_COMMIT`](backend/CORE_COMMIT) +
[`backend/requirements.txt`](backend/requirements.txt) (backend; `/ready` сверяет установленный коммит).

## Быстрый старт (Linux, Python ≥ 3.11, Node 22)

```bash
# backend: API + встроенный воркер на 127.0.0.1:8000
cd backend
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt -e .
scripts/fetch_core.sh
.venv/bin/python -m dd_backend serve --host 127.0.0.1 --port 8000

# UI (в другом терминале): dev-сервер 127.0.0.1:5173 с прокси /api → backend
cd frontend && npm ci && npm run dev
```

Подробности (режимы исполнения `builtin-only` / `trusted-local`, переменные окружения, модель безопасности,
same-origin развёртывание) — в [backend/README.md](backend/README.md).

## Известные ограничения

- Вкладка «Сводная» в UI шлёт устаревшую форму запроса `POST /api/runs/{id}/pivot` и получает 422 —
  см. раздел «Ограничения» в [frontend/README.md](frontend/README.md).
- `trusted-local` исполняет пользовательский Python без sandbox — только на loopback.
- UI не прошёл QA-верификацию (см. матрицу трассировки).
