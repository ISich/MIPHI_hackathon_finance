# Definition of Done и план проверки

Источник подробных ожиданий — [PRD §14](../PRD.md). Эта таблица назначает владельцев и доказательства; **тесты приложения пока не запускались, реализации в docs PR нет**. Статусы M/C/A/Q сохраняются из PRD.

| AC | Primary | Что предъявить |
|---|---|---|
| AC-01 | D2 | real full UI→pipeline→report, D1/D3/D4 помогают |
| AC-02 | D1 | missing pair/JSON/key collision, D2 показывает FAILED |
| AC-03 | D1 | четыре change type на fixture |
| AC-04 | D1 | exclusions on/off |
| AC-05 | D1 | три array modes/composite/model identity |
| AC-06 | D1 | bucket/raw и выбранная type policy; pending Q5 не скрывается |
| AC-07 | D1 | официальный baseline; BLOCKED до его получения |
| AC-08 | D1 | independent decision counts |
| AC-09 | D4 | exact distinct membership/rollups, UI D3 |
| AC-10 | D3 | изменяемая раскладка, не static dashboard |
| AC-11 | D4 | пять unchanged checks и по событию FAIL-test каждому |
| AC-12 | D4 | все MartAPI filters, AND/lists/count/unique IDs |
| AC-13 | D3 | UI code edit/apply процедуры и check, D2 runtime |
| AC-14 | D4 | execution error vs business verdict, LOW/sample |
| AC-15 | D4 | HTML из file:// → правильная сводная, browser D3 |
| AC-16 | D2 | nonblocking status/events/code, UI D3 |
| AC-17 | D2 | два owners/Run, прямой чужой ID, UI D3 |
| AC-18 | D2 | повтор config/snapshots, D1/D4 reproducibility |
| AC-19 | D2 | чистый запуск по README |
| AC-20 | D4 | query timings; D1 normalize/compare, D2 стенд, D3 UI |
| AC-21 | D4 | DEFERRED: пользователь отложил AI до конца |
| AC-22 | D3 | девять шагов демо; участвуют все |

## Gate перед стартом четырёх независимых веток

Назначить D1–D4 людям, выбрать минимальный stack, подтвердить DTO/data/execution contracts. Пока это не сделано, можно параллельно работать над fixtures/tests/логикой, но нельзя считать четыре независимо выбранных backend/frontend/storage совместимыми.

## Проверки каждого PR

Одна ограниченная задача/FR, tests (positive+negative), фактическая команда/вывод, изменённые contracts с review producer+consumer, отсутствие secrets/ПДн/закрытых материалов. «check вернул FAIL» не равно «тест сломан»; сравнивать с ожидаемым событием. UI fixtures не подменяют end-to-end evidence.

## Smoke после интеграции

Dataset → выбранный Python → vertical/comparison/segments → counts → исходные checks → финальная ссылка → pivot cell→APP_ID→атрибут → новая проверка UI→общий отчёт → HTML→сводная. Во время расчёта progress жив; до завершения KPI не публикуются; две сессии не смешиваются. В первом срезе достаточно одной пары и одного check, в финальной приёмке — полный набор и пять.

## Измерения

Приведение/сравнение отдельно от full pipeline; opening/pivot/filter/drill-down/reopen отдельно. Фиксировать commit, hardware, dataset revision, pairs и row counts по слоям, cache состояние. Пороги из PRD §11; без выполнения не писать «зелёный CI» или реальные секунды. Baseline организаторов не заменяется внутренними fixtures.
