# API v0 — предлагаемый стык backend и UI

**A, не реализованный OpenAPI.** Steward D2; D3 подтверждает UI, D4 — reporting payloads. Backend/frontend framework не выбран. Эти маршруты — согласуемая поверхность; перед параллельным кодом превратить в одну машинную схему, а не независимо угадывать поля.

## Предлагаемые ресурсы

| Метод/маршрут | Назначение | Owner логики |
|---|---|---|
| GET /api/datasets | доступные разрешённые наборы и ревизии | D2 |
| POST /api/datasets | регистрация набора в разрешённом registry без смены кода; механизм source согласовать | D2 с D1 |
| GET/POST /api/scripts | доступные Python artifacts/создание из workspace или допустимого .py | D2 |
| GET /api/script-kinds | I/O-контракты, шаблон и пример для normalize/compare/segments/aggregate/check | D2 с D1/D4 |
| GET /api/scripts/{id} | метаданные и доступный текст кода | D2 |
| GET/POST /api/configurations | список/сохранение RunConfig | D2 |
| GET /api/configurations/{id} | повторно открыть сохранённый конфиг | D2 |
| POST /api/runs | создать Run по выбранному конфигу/snapshot | D2 |
| GET /api/runs | список запусков текущей области доступа | D2 |
| GET /api/runs/{id} | status, stage, progress, completeness, готовая report ref | D2 |
| GET /api/runs/{id}/events?after=... | журнал с устойчивым event sequence | D2 |
| GET /api/runs/{id}/code/{stage} | ссылка/текст исполняемого code snapshot в пределах доступа | D2 |
| GET /api/runs/{id}/summary | итоговые показатели, полнота, направления, top changes | D4 |
| POST /api/runs/{id}/pivot | dims/filters → cells, корректные totals, opaque group locators | D4 |
| GET /api/runs/{id}/groups/{group}/applications | APP_ID page + полный distinct total | D4 |
| GET /api/runs/{id}/applications/{app_id} | segments и атрибуты/различия заявки | D4 |
| GET /api/runs/{id}/checks | совместимый alias checks **initial_report_id**, никогда не неявный latest | D4 |
| GET /api/runs/{id}/reports | доступные Report identities/revisions и publication status данного Run | D2/D4 |
| POST /api/runs/{id}/check-runs | новый CheckRun с полным выбранным набором checks на готовых data; возвращает check_run_id, report_id и status URL | D2/D4 |
| GET /api/check-runs/{check_run_id} | status, run_id/data revision, report_id, executions | D2/D4 |
| GET /api/reports/{report_id} | метаданные конкретного неизменяемого отчёта и ссылки на данные/сводную | D2/D4 |
| GET /api/reports/{report_id}/checks | executions и строки именно выбранного Report | D4 |
| GET /api/reports/{report_id}/checks.html | HTML-снимок; ссылка именно на интерактивную сводную этого Run | D4 |
| GET /health /ready | процесс жив / зависимости готовы по согласованной политике | D2 |

GET /script-kinds показывает пользователю контракт/шаблон/пример. POST /scripts + выбор ScriptRef + POST /runs покрывают применение **процедуры**; POST /runs/{id}/check-runs — применение новой **проверки**. Textarea без вызова исполнения не считается рабочей областью. Минимальный предлагаемый путь правки процедуры — новый настоящий Run на явно зарегистрированной маленькой fixture или полном наборе, тем же runner; отдельный preview endpoint и произвольные notebook kernels не обязательны. Длительная операция отвечает accepted identity, не удерживает request весь расчёт. Конкретные HTTP-коды и envelope ниже — предложения.

Report identity фиксируется явно: первый Run хранит initial_report_id, GET /runs/{id}/checks всегда ссылается на него; UI после нового CheckRun открывает возвращённый report_id через /reports/{report_id}/checks. GET /runs/{id}/reports позволяет выбрать старый/новый отчёт, прежний не меняется. HTML строится для конкретного report_id и ссылается на сводную его run_id/data revision с report_id в контексте навигации. Summary/pivot/membership исходного Run не пересчитывают JSON при повторе checks. Неготовый Report возвращает not-ready, а не частичную таблицу.

## Общие правила payload

Везде явные IDs/refs и status по [execution contract](execution.md). Пагинация: items + total + next cursor/offset; один способ выбрать командой. Report query отдаёт revision/run_id, чтобы stale response не заменил данные другого экрана. Не отправлять сотни тысяч source rows ради каждого pivot action. Total в drill-down — полный набор после фильтров, не длина страницы.

Запуск и check-run возвращают identity и status URL. Report data до ready: явная not-ready ошибка, не пустая «успешная» сводка. Предложение: 202 для принятого запуска, 409 для not-ready, 400/422 для невалидного запроса, 401/403 либо скрывающее существование 404 для доступа по принятой политике. Выбрать единообразно, не угадывать на frontend.

Errors: стабильный machine code, message, request/run ref, безопасные details. Traceback доступен владельцу в diagnostics, не в публичном ответе всем. SQL/path expressions напрямую от клиента не исполняются; dimensions/filter operators whitelist. Неизвестный фильтр — явная ошибка, а не игнорирование.

Owner scope проверяется на каждом route, group locator, code artifact и export. Идентификатор владельца из request body не даёт права доступа. Frontend и Python runner не получают ключей инфраструктуры/LLM.

## Контрактная приёмка

D2/D3/D4 согласуют request/response examples и ошибки для каждого используемого route. В первом интеграционном срезе реальные POST Run → GET status/events → summary/checks на одной fixture. UI mocks маркированы и повторяют wire contract; не часть доказательства реального расчёта.

Не добавлять сейчас LLM endpoints: пользователь отложил AI/Codex до завершения ядра. Не путать application `/api` с будущим upstream `/v1` модели.
