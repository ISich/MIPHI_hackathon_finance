# D2 — PRD платформы, исполнения и стенда

**Owner:** D2; **reviewers:** D1/D4 по вызовам этапов, D3 по API. Проектные детали — A. Основные FR: FR-001, FR-003, FR-006, FR-008, FR-014, FR-015, FR-016, FR-018, FR-022, FR-027. Основание: [PRD](../PRD.md), §§8,10–13.

## Результат

Сервер принимает конфигурацию, возвращает run_id без ожидания долгого расчёта, выполняет выбранные процедуры, сохраняет статус/журнал/артефакты и публикует завершённый отчёт. Один общий runner для D1 и D4, не два независимых исполнителя.

## Граница

D2 владеет registry datasets/scripts, RunConfig/Run, owner scope, API infrastructure, physical storage driver/schema, runner/queue, журналом, health/readiness и инструкцией запуска. Не пишет dataset-specific parser, MartAPI query semantics, HTML layout и UI. D4 задаёт reporting queries; D2 обеспечивает их публикацию через общий API/router.

## Требуемые сущности

Dataset (не фиксированный RUN ID), ScriptArtifact (тип, источник, текст/ссылка, параметры), RunConfig (выбор на каждый слот), Run (owner/status/stage), StageEvent, ArtifactRef, CheckRun, Report, CheckExecution. Схемы и lifecycles: [execution](../contracts/execution.md), HTTP-предложение: [API](../contracts/api.md).

## Поведение

- Один источник на каждый обработчик: workspace или .py; разным этапам разрешены разные источники. Сохранять параметры и эффективный код запуска; полноценной истории версий UI не нужно.
- Длинный расчёт вне HTTP/UI потока; ограниченная конкуренция и очередь. Не создавать процесс на каждый лист JSON. Точный worker/storage stack ещё не утверждён.
- Status QUEUED/RUNNING/COMPLETED/FAILED, stage отдельно. Ошибка бизнеса FAIL не меняет status на FAILED автоматически. Ошибка check имеет execution_status, не новый RESULT enum.
- Финализация только после готовых данных/исполнений. Журнал/прогресс доступен во время работы, аналитический отчёт до завершения — нет.
- Сессии/учётки — pending решение; owner scope применяется ко всем API, коду, отчётам, выгрузкам и artifact refs. Не доверять owner_id из JSON клиента как аутентификации.
- Реестр принимает новый датасет той же структуры без изменения backend. Валидация manifest только по используемым полям, не по выдуманной схеме.
- Таймаут/RAM/output limits и отсутствие секретов runner; реальную FS/network isolation не обещать без реализации. Доверенный локальный режим явно маркируется.
- Деплой — только с отдельным разрешением владельца стенда; данный docs PR ничего не разворачивает. ИИ/Codex отложен пользователем до самого конца и не блокирует ядро.

## Задачи

- **D2-01:** согласовать DTO/storage ports/runner input-output с соседями; schema/API steward. Не забирать data semantics у D1.
- **D2-02:** configs/datasets/scripts + owner scope; GET script-kinds с контрактом/шаблоном/примером; создать Run и journal с асинхронным запуском. Передать D3 реальный API быстро.
- **D2-03:** выполнить одну процедуру D1 и один check D4 одним runner; правка процедуры применяется настоящим Run на зарегистрированной маленькой fixture, без отдельного notebook kernel; обработать traceback/timeout/output validation; сохранить artifact refs. MartAPI исполнять в check-worker над read-only snapshot согласно execution contract.
- **D2-04:** полный порядок stages, atomic publication, повтор из config, check-only execution на завершённой витрине через тот же runner.
- **D2-05:** physical persistence/indexes вместе с D1/D4; две независимые сессии; не допускать чужие ID через прямой URL.
- **D2-06:** README чистого запуска, smoke и [runbook](../deployment/runbook.md). Конкретные команды после выбора стека и данных стенда, не фиктивный compose.

## DoD

AC-01/02/13/16–19 совместно; owner AC-16/17/19 и воспроизводимость AC-18. Долгий этап не блокирует status endpoint, отчёт публикуется атомарно; ошибка одной проверки не роняет сервис. Каждая миграция/storage change ревьюится D1/D4 и не перетирает чужой слой. В PR — команды с реальным выводом; deploy readiness отдельно от docs/CI.
