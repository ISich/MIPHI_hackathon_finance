# Контракт исполнения v0 — D2 ↔ D1/D4 ↔ D3

**A: проектный контракт, не выданные организаторами сигнатуры normalize/compare/aggregate.** CHECK/MartAPI — C основного PRD. Steward D2, обязательные reviewers D1/D4/D3.

## Сущности и поля, которые надо зафиксировать в DTO

- **DatasetDescriptor:** dataset_id, доступные срезы, revision/fingerprint, число/идентификаторы пар после валидации. Server paths не принимает от произвольного клиента без проверки разрешённого registry.
- **ScriptRef:** script_id, kind (normalize/compare/segments/aggregate/check), source (workspace/file), выбранный artifact, params. В одном слоте один source; поддерживаются оба канала. Source `file` — размещённый разрешённый `.py`, не unrestricted filesystem path.
- **RunConfig:** config_id, dataset_id, script slots, selected checks + parameters, normalization policy, owner scope. Owner определяется серверной сессией.
- **Run / DataRun:** run_id, config snapshot ref, status, stage, processed, total (может отсутствовать), timestamps, data artifact refs/data revision, initial_report_id, completeness/diagnostics. После финализации data revision неизменна; дополнительные проверки не переписывают Run.
- **CheckRun:** check_run_id, run_id/data revision, report_id, snapshot списка checks/params, status, CheckExecution IDs. Начальное исполнение checks полного Run тоже создаёт CheckRun. Повтор только checks создаёт новый CheckRun и новый report_id на той же data revision.
- **Report:** report_id, run_id/data revision, check_run_id, selected checks/params snapshot, execution refs, completeness, publication status. Готовый Report неизменяемый; новая проверка попадает в новый общий отчёт исходного набора плюс новая, а не правит прежний HTML. По умолчанию полный Run открывает initial_report_id; UI после check-only явно переключается на возвращённый новый report_id, а не угадывает latest.
- **ArtifactRef:** artifact_id, run_id, kind, schema revision, storage-internal locator, row count/fingerprint where applicable. Не отдавать клиенту секретный server path.
- **StageEvent:** run_id, монотонный sequence, stage, procedure ref, event level, processed/total, message, timestamp; ссылка на фактически исполняемый код/его snapshot.
- **CheckExecution:** execution_id, run/data revision, CHECK.id, эффективные params, execution_status, diagnostics, result rows (0…N).

Имена wire-полей уточнить совместно с выбранным стеком; выше — предлагаемая единая семантика. Не генерировать разные версии структуры без синхронизации.

## Жизненный цикл

QUEUED → RUNNING → COMPLETED или FAILED. Stage: VALIDATING → NORMALIZING → COMPARING → AGGREGATING → CHECKING → FINALIZING. Отдельный segments-обработчик, если выбран, исполняется как именованный substep COMPARING после сопоставления и до AGGREGATING; в журнале отдельное событие/code ref. AGGREGATING сохраняет BaseFacts/BaseMembership фиксированной детализации из data.md; выбор пользовательской раскладки идёт позднее запросом server rollup и не перезапускает процедуру. Status и stage — не один enum. ИИ обогащение после ядра, отложено до конца, отдельное состояние.

COMPLETED означает завершённые выбранные этапы и доступность опубликованного отчёта, но не «все бизнес-checks PASS». При технической ошибке check допускается финальный отчёт с явно неполным check execution, согласно PRD §10; позитивный AC-11 при этом не пройден. Для такой полноты использовать отдельное поле/диагностику, не молчаливо «всё успешно».

## Вызов процедур

D2 получает input artifact refs и effective params, открывает разрешённые данные runner, вызывает выбранный callable, валидирует выходную схему, сохраняет результат/диагностики, завершает stage и передаёт refs следующему этапу. Конкретные Python function names для normalize/compare/aggregate согласовать до кода; не выдавать их за источник задания. Данные передаются batch/iterator/хранилищем по выбранному формату, не процессом на лист.

Выданные checks импортируются целым файлом: объект CHECK содержит id/label/params/entrypoint, вызов entrypoint(mart, params) возвращает list[dict]. Значения RESULT только PASS/FAIL. Ошибка импорта/отсутствующий CHECK, невалидный entrypoint и дубликат CHECK.id диагностируются до исполнения; дубли не затирают прошлый check. Exception/TIMEOUT/INVALID_OUTPUT — execution_status, не поддельная строка FAIL. Empty successful result отражается как success с 0 строк, не выдуманный PASS. Params копируются между запусками.

**A, стык MartAPI/runner:** для первого прототипа D2 даёт check-worker read-only snapshot артефактов конкретного Run, а D4 реализует MartAPI внутри worker поверх него без server DB credentials и без доступа к другим Run. Индексы строятся/подключаются в пределах разрешённого snapshot; Query API сервера остаётся отдельным consumer того же data contract. Если выбран иной backend storage и требуется RPC broker, это отдельное согласованное решение D2/D4 до реализации, с теми же фильтрами/run scope; не передавать секретную DB connection пользовательскому коду. Реальная защита read-only/изоляции зависит от выбранного trust mode, а не Python-обёртки.

## Ошибки, публикация, параллелизм

Непарный input/невалидный JSON/ключи/обязательная выходная схема → FAILED, явные диагностики, не частичный отчёт как полный. Ошибка одного check не роняет API и другие независимые checks; storage/aggregation failure не публикует ложный отчёт. Прогресс после сохранения события; отсутствие total не подменять процентом.

Run snapshot immutable для исполнения. При повторном создании HTTP-запроса UI не создаёт дубли молча: D2/D3 согласуют idempotency или блокировку повторной отправки. Одновременные owners/Run не разделяют mutable globals/DEFAULTS/temp-paths. Check-only run использует завершённую data revision и новый report identity, прежний отчёт не переписывается.

Изоляция процесса, wall/RAM/output limits и правила secrets задаются D2. File/network sandbox — отдельная явно проверяемая возможность, не следствие отдельного cwd. См. PRD §12.
