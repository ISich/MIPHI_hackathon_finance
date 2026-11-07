# QA-набор: контракты и интеграционные/приёмочные тесты

Ветка `test/contracts-night`. Код приложения не меняется; здесь только тесты, фикстуры и скрипты.
Матрица трассировки требований: [requirements-traceability.md](requirements-traceability.md).

## Что внутри

| Путь | Что проверяет | Что нужно для запуска |
|---|---|---|
| `tests/contracts/` | Ядро D1 и D4 (`decision_diff` @ 496d8cd): MartAPI по S5, `check_runner`, 5 исходных checks на событийных фикстурах, HTML-экспорт, семантика сравнения AC-02…AC-08 | только Python |
| `tests/http/` | Black-box HTTP: health/ready/openapi, асинхронный Run, изоляция владельцев, path traversal, снимки, идентичность отчётов, FAIL / ошибка исполнения / 0 строк, user code | запущенный backend на loopback (`QA_BASE_URL`) |
| `tests/restart/` | Run, прерванный SIGKILL сервера | `QA_BACKEND_DIR` (тест сам поднимает и гасит свой сервер) |
| `tests/support/fixtures.py` | Синтетические ответы СПР и прогон **настоящего** конвейера: CLI ядра → D4 storage → DuckDBMart | — |
| `scripts/fetch_core_checks.sh` | Выкладывает 5 checks и examples из pinned commit (`git archive`) в `.cache/` | git, доступ к origin |
| `scripts/make_http_fixtures.py DIR` | Наборы `neutral`, `events`, `broken`, `badjson` и symlink `escape` для HTTP-тестов | — |
| `scripts/run_http_suite.sh MODE [pytest args]` | Поднимает backend на 127.0.0.1:18765 с временным `DD_HOME`, гонит тесты, гасит **только свой** процесс | `BACKEND_DIR` |
| `scripts/qa_servers_alive.sh` | Показывает, не остался ли запущенным QA-сервер | — |

Моков ядра нет. Пользовательские check-файлы в тестах — это **входные данные**, а не двойники ядра. Единственный двойник в смежном коде — `SimpleMart` в тестах самой ветки SomeShit; в этой ветке он не используется.

`xfail(strict=True)` с `DISC-NN` / `API-DISC-NN` — это задокументированное расхождение с контрактом. Когда владелец его исправит, тест станет XPASS и упадёт, и маркер нужно будет снять.

## Команды

```bash
python3 -m venv .venv                      # нужен пакет python3-venv
.venv/bin/python -m pip install -r requirements-qa.txt
scripts/fetch_core_checks.sh               # один раз; нужен fetch origin SomeShit

# 1) offline-контракты ядра/D4 (~15 с)
.venv/bin/python -m pytest tests/contracts -q

# 2) HTTP против локально поднятого backend (оба режима исполнения)
BACKEND_DIR=../MIPHI_hackathon_finance/backend scripts/run_http_suite.sh builtin-only tests/http -q
BACKEND_DIR=../MIPHI_hackathon_finance/backend scripts/run_http_suite.sh trusted-local tests/http -q

# 2b) HTTP против уже запущенного backend (только loopback); synthetic-наборы — если root указывает на DIR
QA_BASE_URL=http://127.0.0.1:8000 [QA_FIXTURE_ROOT=qa QA_FIXTURE_DIR=DIR] .venv/bin/python -m pytest tests/http -q

# 3) restart
QA_BACKEND_DIR=../MIPHI_hackathon_finance/backend .venv/bin/python -m pytest tests/restart -q -s

scripts/qa_servers_alive.sh                # должно ничего не вывести
```

Без `QA_BASE_URL` HTTP-тесты пропускаются с пометкой NOT VERIFIED, а адрес не на loopback прерывает запуск.

`trusted-local` исполняет пользовательский Python **без sandbox**. Использовать только на 127.0.0.1 и только с собственными тестовыми скриптами.

## Переменные

`CORE_SHA` (по умолчанию 496d8cd…), `CORE_CHECKS_DIR`, `QA_BASE_URL`, `QA_FIXTURE_ROOT`, `QA_FIXTURE_DIR`, `QA_EXAMPLES_ROOT` (по умолчанию `examples`), `QA_RUN_TIMEOUT` (по умолчанию 300 с), `QA_BACKEND_DIR`, `QA_PORT` (по умолчанию 18765), `BACKEND_PY`.
