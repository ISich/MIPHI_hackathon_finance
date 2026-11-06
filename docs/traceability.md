# Трассировка требований и владельцев

**Статус:** предложение ответственности, не назначение людям. Primary owner один; соседние роли участвуют по контрактам. Источник всех ID — [PRD](PRD.md). Нет отменённых FR.

| FR | Primary | Модуль |
|---|---|---|
| FR-001 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-002 | D1 | [D1](modules/01-data-engine.md) |
| FR-003 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-004 | D1 | [D1](modules/01-data-engine.md) |
| FR-005 | D1 | [D1](modules/01-data-engine.md) |
| FR-006 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-007 | D3 | [D3](modules/03-web-workspace.md) |
| FR-008 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-009 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-010 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-011 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-012 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-013 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-014 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-015 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-016 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-017 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-018 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-019 | D1 | [D1](modules/01-data-engine.md) |
| FR-020 | D1 | [D1](modules/01-data-engine.md) |
| FR-021 | D1 | [D1](modules/01-data-engine.md) |
| FR-022 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-023 | D3 | [D3](modules/03-web-workspace.md) |
| FR-024 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-025 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-026 | D4 | [D4](modules/04-checks-reporting.md) |
| FR-027 | D2 | [D2](modules/02-platform-runtime.md) |
| FR-028 | D4 | [D4](modules/04-checks-reporting.md) |

## NFR

| NFR | Primary | Участие |
|---|---|---|
| NFR-001 | D1 | D2 оркестрация, D4/D3 полный путь |
| NFR-002 | D4 | D1 cardinality, D2 storage, D3 UI |
| NFR-003 | D1 | D2 hardware/runtime; D4 query timings, D3 browser timings |
| NFR-004 | D1 | baseline от организаторов, D4 invariants |
| NFR-005 | D2 | D3 два browser sessions, D4 run scope |
| NFR-006 | D2 | выбранная trust policy; AI secrets отдельно |

AC-01…AC-22 распределены по одному primary в [плане приёмки](quality/acceptance.md). FR-024/AC-21 **DEFERRED** пользователем; сохранены, не объявлены реализованными или снятыми с оценки. Имена D1–D4 остаются ролями до назначения команды.
