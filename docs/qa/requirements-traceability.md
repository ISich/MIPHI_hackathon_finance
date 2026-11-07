# Матрица трассировки: требования → тесты → статус

> **Статус документа (сверено с `main` @ 010f42a, 07.11.2026):** это зафиксированный срез прогона на backend `eb0053f` / QA `cddd1a7`, полностью **не перепрогонялся** на текущем `main`. После него в `main` влиты: валидация вывода процедур (`OUTPUT_SCHEMA_INVALID`, PR #7, [backend-output-validation-review.md](backend-output-validation-review.md)) и исправление гонки старта supervisor при остановке (PR #8, [backend-shutdown-recovery-review.md](backend-shutdown-recovery-review.md)); ядро по-прежнему 421da26. Backend, frontend и QA теперь в одном репозитории (`backend/`, `frontend/`, `tests/`). UI по-прежнему не верифицирован; известно, что вкладка «Сводная» UI не согласована со схемой `POST /pivot` (422, см. `frontend/README.md`). Для статусов на текущем SHA — перепрогнать набор.

Ночь/день 07.11.2026, night-qa. Проверялся **актуальный код**, не документы. Статусы ниже относятся **только** к этому сочетанию SHA (прогон 17:34 МСК, после исправлений по Codex CR #1–#5):

- QA-ветка: `test/contracts-night` @ `cddd1a7` (+ последующий docs-коммит);
- ядро D1 + D4: `origin/SomeShit` @ **`421da26caf030ce230778ffbd07ee1f72bf71217`** (единый pin в `CORE_COMMIT`; установленный пакет проверяется тестом `contracts/test_core_pin.py`);
- backend D2: опубликованный `feat/backend-night` @ **`eb0053f`** (его CORE_COMMIT = 421da26 = установленное ядро), read-only снимок через `git archive`, на 127.0.0.1 в обоих режимах. На 60a61fd прогон блокировался: `EXECUTION_UNCONTAINED` (containment не подтверждён) → очередь заблокирована; на eb0053f — 0 таких событий.

Поправка к прежним редакциям: прогоны 11:35–12:16 МСК шли на снимке backend 9546f5d/cc8fc9c с **установленным** ядром 421da26 (не 496d8cd, как было указано).

На другом SHA backend или ядра статусы нужно получить заново.
- UI (D3) **не проверялся** — всё, что требует браузера, помечено NOT VERIFIED.

Источник ID — `docs/PRD.md` (ветка `docs/implementation-foundation`, 3731ae3). Связь «задание → FR» взята из `night-orchestration/docs/requirements-traceability.md`.

DISC-03, DISC-04 и API-DISC-02 **закрыты** реальным pivot/BaseFacts (ядро 421da26, backend f617212). DISC-05 (вложенные параметры) **отозван**: в реальном жизненном цикле `run_checks` утечки нет (CR #9). Добавлен API-DISC-05.

Статусы:

- **PASS**: требование проверено исполняемым тестом на реальном коде, без моков ядра.
- **PARTIAL**: проверена часть; недостающее названо.
- **FAIL**: есть воспроизводимое расхождение (DISC / API-DISC, тест `xfail(strict)`).
- **NOT VERIFIED**: не проверялось этой ночью; причина указана.
- **DEFERRED**: отложено решением пользователя.

Пути тестов указаны относительно `tests/`. `C` = offline-контракты ядра/D4, `H` = black-box HTTP, `R` = restart.

## Функциональные требования

| ID | Требование (кратко) | Тесты | Статус | Комментарий |
|---|---|---|---|---|
| FR-001 | Выбор набора и запуск из приложения; новый набор без правки кода | H `http/test_runs_async.py` (весь модуль), `http/test_path_traversal.py` | PASS (API) | Регистрация через `POST /api/datasets` в allowlisted root; новый root — env `DD_DATA_ROOTS` без правки кода. UI — NOT VERIFIED |
| FR-002 | Сопоставление по имени, полнота пар, без скрытых потерь | C `contracts/test_core_contract.py::test_ac02_*`; H `test_missing_pair_and_invalid_json_fail_the_run`, `test_invalid_json_fails_the_run` | PASS | Ядро-CLI само пишет только issues.json, exit 0 (OBS-02); backend переводит Run в FAILED (`INPUT_MISSING_PAIR`). Проверка manifest — NOT VERIFIED |
| FR-003 | Последовательность этапов | H `test_events_monotonic_and_follow_stage_order` | PASS | VALIDATING→…→FINALIZING; SEGMENTS — substep COMPARING |
| FR-004 | 4 CHANGE_TYPE; DIFF_FLAG по VALUE, не по бакету | C `test_ac03_*`, `test_ac06_value_change_inside_bucket_is_not_lost`, `test_mart_contract.py::test_diff_flag_zero_only_for_same` | PASS | |
| FR-005 | Вертикальный UNION, парное представление, facts + связи с APP_ID | C `test_mart_contract.py`, `test_base_facts_have_change_type_dimension`, `test_pivot_drilldown_matches_fact_cnt` | PASS | D4 base_facts (421da26): BaseFacts c CHANGE_TYPE и segments, BaseMembership, CNT == |membership| |
| FR-006 | Конфиг сохраняется и повторяется | H `test_config_and_code_snapshot_survive_script_edit`, `test_idempotent_replay_and_key_reuse` | PASS (API) | |
| FR-007 | Интерактивная область **и** `.py`; один источник на слот | H `test_user_code.py::test_example_procedures_run_in_every_slot`, `test_uploaded_py_check_runs` | PASS (API, trusted-local) | В режиме по умолчанию `builtin-only` пользовательский код явно запрещён (403 `CUSTOM_EXECUTION_DISABLED`). UI-редактор — NOT VERIFIED |
| FR-008 | Контракт, шаблон, пример, валидация до запуска | H `test_script_kinds_publish_contract_template_example`, `test_syntax_error_rejected_before_run` | PASS | |
| FR-009 | 5 checks без изменения исходников; параметры редактируются | C `test_organizer_checks_events.py` (10 тестов); H `test_events_dataset_builtin_checks_fail_with_expected_app_ids`, `test_check_params_from_config_are_applied` | PARTIAL | Исполнение и FAIL на событиях — PASS. Встроенные checks отдают `params={}` вместо DEFAULTS, и UI нечего показать для редактирования (API-DISC-03) |
| FR-010 | HTML checks + абсолютная ссылка на сводную этого Run | C `test_html_report_contract.py`; H `test_report_html_links_to_this_run` | PARTIAL | Ссылка абсолютная и ведёт на `/runs/{run_id}/reports/{report_id}`. В тексте HTML нет Run ID / report_id / параметров / пометки неполноты (DISC-10, DISC-11). Открытие из file:// в браузере — NOT VERIFIED |
| FR-011 | Пользователь меняет раскладку сводной; distinct-итоги | H `test_pivot_rollup_with_user_layout`, `test_pivot_cells_carry_locators_and_member_totals` | PASS (API) | Реальный server rollup на f617212; total ячейки = distinct membership, сверено с фикстурой. UI — NOT VERIFIED |
| FR-012 | Drill-down ячейка → APP_ID → заявка; пагинация без потери total | C `test_pivot_drilldown_returns_full_distinct_total`; H `test_pivot_cells_carry_locators_and_member_totals`, `test_drilldown_returns_full_distinct_total`, `test_application_card` | PASS (API) | groups/{locator}/applications: полный total, пустая страница за границей сохраняет total |
| FR-013 | Первый экран: всего, с различиями, смена решения, **направления**, без смены решения, полнота | H `test_summary_core_metrics`, xfail `test_summary_has_decision_directions` | PARTIAL | Нет направлений APPROVE→REJECT / REJECT→APPROVE и числа «различия без смены решения» (API-DISC-01) |
| FR-014 | Журнал этапов: время, объём, обработчик, переход к коду | H `test_stage_start_events_reference_code`, `test_code_snapshot_of_executed_procedure` | PASS | |
| FR-015 | Не блокирует UI; неизвестный total не выдаётся за % | H `test_not_ready_before_completion_and_status_stays_responsive` | PASS (API) | Status/health отвечают < 2 с во время Run. UI — NOT VERIFIED |
| FR-016 | Несколько пользователей, области не смешиваются | H `test_owner_isolation.py` (7), `test_two_sessions_run_concurrently_without_mixing` | PASS (API) | Анонимные серверные сессии; это не IAM |
| FR-017 | Нет промежуточных KPI | H `test_not_ready_*`, `test_failed_run_report_data_is_not_served_as_success` | PARTIAL | `/summary` во время Run всегда 409 `NOT_READY`. Но `/runs/{id}/checks` отдаёт 200 с отчётом, пока Run ещё CHECKING/FINALIZING (API-DISC-05). Ожидаемый отказ засчитывается, только если ранний ответ — точная копия опубликованного начального отчёта этого Run; иначе это FAIL |
| FR-018 | Подмена процедуры/check без пересборки | H `test_example_procedures_run_in_every_slot`, `test_new_check_joins_original_five_in_new_common_report` | PASS (trusted-local) | |
| FR-019 | Исключения по умолчанию, видимы и изменяемы | C `test_ac04_exclusions_on_and_off`; H xfail `test_exclusions_editable_with_builtin_normalize` | PARTIAL | В ядре работает; через API изменить можно только своей normalize-процедурой (trusted-local) (API-DISC-04) |
| FR-020 | Три режима массивов | C `test_ac05_*` (3), `test_unconfigured_array_and_duplicate_identity_fail_loudly` | PASS | Режим value покрыт тестами самого ядра (TEACHING) |
| FR-021 | DECISION_* из decisionResult.decision | C `test_ac08_decision_changed_from_decision_result_not_offers` | PASS | |
| FR-022 | Запуск на чистой машине по README | — | NOT VERIFIED | backend README не проверялся с чистой машины; нужен python3-venv (OBS-03) |
| FR-023 | Новая проверка в приложении → общий отчёт | H `test_new_check_joins_original_five_in_new_common_report` | PASS (API, trusted-local) | Демонстрация в UI — NOT VERIFIED |
| FR-024 | ИИ-мнение | — | DEFERRED | Отложено пользователем (DEC-06) |
| FR-025 | Техническая ошибка ≠ PASS/FAIL | C `test_check_runner_contract.py`; H `test_check_outcomes.py` (8) | PASS (backend) / PARTIAL (D4 runner) | Backend: SUCCEEDED / ERROR / TIMEOUT / INVALID_OUTPUT. Сам `check_runner` D4 без статусов и таймаута (DISC-06, DISC-07) |
| FR-026 | Check-only: новый ID и отчёт, старый не меняется | H `test_initial_report_is_stable_and_check_only_creates_new_identity`, `test_new_check_joins_*` | PASS | |
| FR-027 | Снимок конфига и кода при старте | H `test_config_and_code_snapshot_survive_script_edit` | PASS (trusted-local) | Правка сразу после accept не влияет; следующий Run берёт новую версию |
| FR-028 | CNT ≠ число APP_IDS в UI | C `test_rows_satisfy_organizer_row_contract` | NOT VERIFIED (UI) | В данных CNT полный, APP_IDS ограничен `app_ids_limit`. Отображение — задача UI |

## Нефункциональные требования

| ID | Тесты | Статус | Комментарий |
|---|---|---|---|
| NFR-001 | `scripts/full_dataset_run.py` | PASS (API) | Открытый набор RUN-20260827-0001, 2002 пары / 4004 JSON: Run COMPLETED, 0 missing/invalid, все 5 checks SUCCEEDED; summary API == независимый CLI ядра |
| NFR-002 | `scripts/full_dataset_run.py` | PARTIAL | Открытый набор: 572 221 вертикальных строк, 289 533 comparison, 44 524 pivot_facts. 20 000 заявок не проверялись |
| NFR-003 | `scripts/full_dataset_run.py` | PARTIAL (замер, не норматив) | Машина: 8 CPU, Python 3.12.3. CLI ядра (normalize+compare+segments+aggregate+CSV) 16,9 с. Run через API: accept 0,9 с, accept→COMPLETED 55,5 с, из них AGGREGATING (CSV + DuckDB mart) ≈ 41,9 с, CHECKING ≈ 3,2 с. Планки PRD не сверялись |
| NFR-004 | — | BLOCKED | Нужен эталон организаторов |
| NFR-005 | H `test_owner_isolation.py`, `test_two_sessions_run_concurrently_without_mixing` | PASS (API) | |
| NFR-006 | H `test_custom_checks_refused_explicitly_when_execution_disabled`, `test_config_and_code_snapshot_*` (ветка builtin-only) | PASS (политика) | По умолчанию builtin-only; trusted-local — явный opt-in. Изоляция Python как sandbox **не** проверялась и не заявляется |

## Критерии приёмки

| AC | Тесты | Статус |
|---|---|---|
| AC-01 | `scripts/full_dataset_run.py` | PASS через API (2002 пары, 4004 файла, финальный отчёт и ссылки); через UI — NOT VERIFIED |
| AC-02 | C `test_ac02_*`; H `test_missing_pair_*`, `test_invalid_json_*`, `test_failed_run_report_data_*` | PASS (API) |
| AC-03 | C `test_ac03_*`, `test_mart_contract.py` | PASS |
| AC-04 | C `test_ac04_*` | PASS (ядро) / PARTIAL (через приложение, API-DISC-04) |
| AC-05 | C `test_ac05_*` | PASS |
| AC-06 | C `test_ac06_*` | PASS; политика `1` и `"1"` даёт SAME (OBS-01, Q5 открыт) |
| AC-07 | — | BLOCKED (эталон) |
| AC-08 | C `test_ac08_*`; независимое чтение `decisionResult.decision` из 4004 JSON | PASS: 385 смен (273 APPROVE→REJECT, 112 REJECT→APPROVE), APPROVE 657→496; совпадает с segments/summary API |
| AC-09 | C `test_pivot_drilldown_*`, `test_base_facts_*`; H `test_pivot_cells_carry_locators_and_member_totals` | PASS (API) |
| AC-10 | H `test_pivot_rollup_with_user_layout`, `test_pivot_cells_*` | PASS (API); изменяемая раскладка в UI — NOT VERIFIED |
| AC-11 | C `test_organizer_checks_events.py`; H `test_events_dataset_builtin_checks_fail_with_expected_app_ids` | PASS |
| AC-12 | C `test_mart_contract.py` (24 PASS) | PASS; DISC-01, DISC-02 — мелкие отклонения |
| AC-13 | H `test_user_code.py` | PASS (API, trusted-local); UI — NOT VERIFIED |
| AC-14 | C `test_check_runner_contract.py`; H `test_check_outcomes.py` | PASS (backend); D4: APP_IDS вне Run не отклоняются (DISC-08) |
| AC-15 | C/H HTML-тесты | PARTIAL (ссылка да; Run ID в тексте нет; file:// в браузере NOT VERIFIED) |
| AC-16 | H `test_not_ready_*`, `test_stage_start_events_*`, `test_config_and_code_snapshot_*` | PASS (API); API-DISC-05 для `/checks` до COMPLETED |
| AC-17 | H `test_owner_isolation.py` | PASS (API); UI — NOT VERIFIED; Python-изоляция — NOT VERIFIED |
| AC-18 | H `test_config_and_code_snapshot_*`, `test_summary_comes_from_real_core`; полный прогон | PARTIAL: на открытом наборе sha256 артефактов comparison/normalized_union/pivot_facts/segments из Run совпали с хешами отдельного CLI-прогона (core-verification.md); построчная сверка двух Run через API не делалась |
| AC-20 | полный прогон | PARTIAL: реальные времена и машина зафиксированы (см. NFR-003), без сопоставления с планками |
| AC-19 | — | NOT VERIFIED |
| AC-21 | — | DEFERRED |
| AC-22 | — | NOT VERIFIED (UI) |

## Дополнительно проверено (вне FR, из execution.md / BACKEND_NIGHT_TASK)

| Что | Тест | Статус |
|---|---|---|
| health / ready / openapi, все маршруты api.md в OpenAPI | H `test_system.py` | PASS |
| Единый error envelope, request_id, без эха ввода | H `test_unknown_route_*`, `test_validation_error_*` | PASS |
| Path traversal / symlink на валидный внешний набор (с положительным контролем) / имена загрузок с проверкой ФС / path-параметры | H `test_path_traversal.py` | PASS |
| Политика исполнения с canary: хранение/загрузка/правка не исполняют код; 4 слота, checks в Run, check-only → 403 `CUSTOM_EXECUTION_DISABLED` без canary | H `test_execution_policy.py` | PASS (builtin-only); положительный контроль canary — trusted-local |
| Подмена владельца заголовком (одинаковое значение у двух сессий), ссылки на чужие dataset/процедуры/checks | H `test_owner_isolation.py` | PASS |
| Изоляция query-эндпоинтов: pivot, pivot-facts, drill-down (A — контроль, B — 404 без данных A) | H `test_query_endpoints_are_owner_scoped` | PASS |
| Изоляция groups/{locator}/applications с **реальным** локатором A | H `test_group_locator_is_owner_scoped` | PASS (f617212) |
| Изоляция скачивания артефакта и `/check-runs/{id}/code/{slot}` | H `test_artifact_download_and_check_run_code_are_owner_scoped` | PASS |
| Сила тестов: мутационные selftests и лаунчеры | `selftest/` (14) | PASS |
| Idempotency-Key: повтор = тот же Run, другой body = 409 | H `test_idempotent_replay_and_key_reuse` | PASS |
| Перезапуск сервера посреди Run | R `restart/test_restart_persistence.py` | PASS (FAILED/RUN_INTERRUPTED) |
| Run без checks помечен NO_CHECKS_SELECTED | H `test_technical_run_without_checks_is_marked` | PASS |
