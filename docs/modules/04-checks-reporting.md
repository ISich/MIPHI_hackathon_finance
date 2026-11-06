# D4 — PRD MartAPI, проверок и аналитических отчётов

**Owner:** D4; **reviewers:** D1 по семантике и fixtures, D2 по storage/runner, D3 по DTO. Основание: [PRD](../PRD.md) §§6,8–9,14. Primary FR-009,010–013,017,024–026,028. ИИ отложен до конца по решению пользователя.

## Результат и границы

Из завершённых normalized/comparison/segments получить корректные facts/membership, выполнить неизменённые checks через MartAPI и отдать summary, pivot, drill-down и HTML. D4 не заводит отдельный runner, user auth или второй DB driver; использует D2. Факты подготавливает выбираемая пользовательская Python-процедура, не незаменяемый parser backend.

## Контракт и правила

- MartAPI буквально по PRD §8.3: rows/count/app_ids/segments/total_apps; фильтры через AND, lists где заданы. count = строки; app_ids = sorted unique. Run scope не зависит от случайного текущего глобального объекта.
- Пять checks исполняются как есть через CHECK/entrypoint(mart, params); params копируются. Имена/исходники нельзя править молча. Кастомные улучшения — отдельный CHECK.id.
- Результат строки PASS/FAIL, уверенность HIGH/LOW; execution errors/empty success отдельно. FAIL на dataset может быть ожидаемым корректным результатом, не дефектом исполнения.
- Serializer true/false/NULL, PATH и rules ARRAY_KEY должны совпасть с ожиданием исходников. Успешный импорт без событийного FAIL-test недостаточен.
- Facts CNT = distinct APP_ID; totals пересчитываются по membership, не SUM по SOURCE/атрибутам/продуктам. Для каждой ячейки group locator восстанавливает ровно её множество ID.
- Drill-down checks показывает переданные APP_IDS и truncation. Для произвольного check не выдумывать полное membership из 20 примеров. Для pivot membership всегда полное.
- HTML содержит Run identity, все строки, LOW, execution diagnostics и абсолютный URL сводной; пользовательский текст экранируется. Доступ к экспорту сохраняет owner scope.
- Новую проверку на готовой витрине D2 запускает как новый CheckRun/Report, включая исходный выбранный набор плюс новую; UI открывает явный report_id, исходный initial_report_id не меняется.
- Ограничения external_score_drift/target_model_changed/stop_factor раскрыты в PRD §8.4; не обещать строгую причинность или результаты, которых check не возвращает.

## Задачи

- **D4-01:** на минимальной fixture D1 реализовать MartAPI и все фильтры; для каждого выданного check отдельная событийная fixture, ожидаемый FAIL и ID. Это можно начать до полного normalizer.
- **D4-02:** интеграция CHECK с runner D2; schema validation, errors/timeouts/empty result, parameters UI DTO.
- **D4-03:** агрегатор сохраняет BaseFacts/BaseMembership фиксированной детализации на AGGREGATING; server query сворачивает их membership под раскладку и возвращает group locator; exact distinct rollups и paging. Согласовать storage indexes с D2.
- **D4-04:** summary/pivot/app details/check report query contracts с D3; endpoints публикует общий API слой D2, бизнес-обработчики владеет D4.
- **D4-05:** HTML export, LOW и truncated-ID UI metadata; check-only report с D2/D3.
- **D4-06:** измерить queries/MartAPI, негативные тесты, полное сравнение membership. После готового ядра — [ИИ-подмодуль](05-ai-opinion.md), не дополнительный пятый разработчик.

## DoD

Owner AC-09/11/12/14/15 и отчётная часть AC-20; AC-21 отложен до конца. В tests проверены все фильтры, четыре CHANGE_TYPE, сортировка/уникальность IDs, business FAIL vs execution failure, точное множество drill-down. На полном наборе пять checks завершаются корректно, но не обязаны выдать только PASS. Никакой fixture не выдается за эталон жюри.
