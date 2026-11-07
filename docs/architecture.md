# Структура реализации

**A: предложение, до соглашений команды.** Основание: PRD §§6–8, 10–13.

## Компоненты и направление зависимостей

```text
D3: Web UI + Python workspace
              ↓ согласованный API
D2: API / owner scope / RunConfig / orchestration / runner
              ↓ вызывает выбранные обработчики
D1: user-code normalize / compare / segments
              ↓ записывает контрактные артефакты
    vertical normalized + comparison view + segments
              ↓ доступ через согласованные storage ports
D4: aggregate facts + membership / MartAPI / checks / report queries / HTML
              ↓
D3: summary / pivot / applications / checks
```

Оркестрация всегда у D2. D4 не заводит второй планировщик для checks. D1 и D4 не встраивают dataset-specific пути в незаменяемый backend: начальные процедуры — заменяемые Python-артефакты в user-code. Хранение общее, но физическая схема и драйвер имеют одного ответственного D2; D1/D4 задают логические схемы и запросы. Передача данных между этапами идёт ссылками на артефакты, а не HTTP-запросом на каждый лист JSON.

## Предлагаемое дерево будущего монорепозитория

```text
repo/
  docs/                         # этот пакет
  contracts/                    # согласованные машинные схемы/типы, steward D2
  backend/
    platform/                   # D2: owners, configs, datasets registry, runs
    execution/                  # D2: runner, queue, snapshots, diagnostics
    storage/                    # D2: physical schema/driver/migrations
    reporting/                  # D4: summary/pivot/membership/drill-down
    mart/                       # D4: реализация MartAPI
    checks/                     # D4: адаптер контрактов/check results
    exports/                    # D4: HTML и ссылки в сводную
  frontend/                     # D3: все UI-компоненты и API client
  user-code/
    processing/                 # D1: normalize/compare/segments
    aggregation/                # D4: заменяемая процедура facts
    checks/                     # D4: выданные unchanged + авторские отдельно
  tests/
    data/                       # D1
    platform/                   # D2
    reporting/                  # D4
    e2e/                        # D3 с fixtures/ожиданиями D1/D4
    fixtures/                   # маленькие синтетические данные без ПДн
  deployment/                   # D2; формат после данных о стенде
  README.md                     # D2; вклад всех владельцев
```

В ветке `core` уже есть библиотека `decision_diff/` в корне; [статус интеграции](implementation-status.md). Сохранить её и использовать заменяемые adapters/wrappers к существующим функциям, не переносить и не переписывать пакет ради предложенного дерева. Это дерево — целевые зоны ответственности платформы, а не требование нового parser. Оно не создано как пустая «реализация» и не подразумевает микросервисы. До выбора стека не добавлять фиктивные package manifests, рабочие endpoints или docker-compose, который невозможно проверить.

## Критические решения

- Вертикальное хранение + comparison view для MartAPI — A/Q2 основного PRD. Нельзя заменить vertical UNION горизонтальной таблицей без решения.
- Reports и checks читают завершённые артефакты одного Run; владение проверяет D2, область данных обязан сохранять D4.
- Агрегат содержит locator группы, который восстанавливает точное множество APP_ID. Пагинация не меняет счётчик; totals distinct не считаются суммой непересекающимися только на вид ячейками.
- Технический статус check отделён от PASS/FAIL строки. Один Run может быть завершён с диагностикой неполных checks, но это не прохождение позитивной приёмки пяти checks.
- LLM — дополнительное обогащение отчёта после checks; статус объёма не утверждён. Секреты модели не попадают в пользовательский runner.
- Файловые данные и DB credentials не отдаются UI. Подпроцесс не равен песочнице; режим доверия должен быть выбран явно.
