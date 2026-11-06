# Хакатон — этап 2: Segments и агрегированный отчёт

Исходники лежат в `decision_diff/` непосредственно в корне, **без** `src/`.

## Что добавлено

- `decision_diff/segments.py`: создание одной строки Segments на каждую валидную пару JSON.
- `decision_diff/reporting.py`: `summarize()` и `pivot_facts()`.
- `tests/test_reporting.py`: 3 новых теста.
- `decision_diff/cli.py`: дополнительно сохраняет `segments.csv`, `pivot_facts.csv`, `summary.json`.
- `pyproject.toml`: поиск пакета в корне проекта.

## Быстрый старт (PowerShell)

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -v
python -m decision_diff.cli --before examples/I32554354_other.json --after examples/I32554354.json --out outputs/demo
Get-Content outputs/demo/summary.json
```

На этой демонстрационной паре BEFORE задан через `I32554354_other.json` (REJECT), AFTER — через `I32554354.json` (APPROVE).

## Полный датасет

```powershell
python -m decision_diff.cli `
  --before "../ЗАДАНИЕ/data/RUN-20260827-0001/RESULTS/BEFORE_MASTER" `
  --after "../ЗАДАНИЕ/data/RUN-20260827-0001/RESULTS/AFTER_BETA" `
  --out outputs/full_run
Get-Content outputs/full_run/summary.json
Get-Content outputs/full_run/issues.json
```

Проверяйте наличие всех пар файлов, количество исключённых пар и диагностические ошибки. Данный архив не содержит полный датасет.

## Что пока не реализовано

- DuckDB и MartAPI (`rows`, `count`, `app_ids`, `segments`, `total_apps`).
- Исполнение пяти внешних проверок и HTML-отчёт.
- Многопользовательский backend/worker и веб-интерфейс.

## Важные оговорки

- В `segments.py` поля `PD_MODEL_*`, `CUTOFF_*`, `PARTNER_TYPE`, `ROUTING_METHOD` относятся к **репрезентативному продукту**, выбранному детерминированно: по первому офферу, а если офферов нет — по сортированному идентификатору продукта. В заявке с несколькими продуктами это упрощение, которое необходимо проверить на всём датасете и согласовать по предметной логике. Все продуктовые детали остаются в сравнении атрибутов.
- `pivot_facts.csv` — агрегаты по группам атрибутов; `CNT` нельзя суммировать по всем путям, чтобы получить число заявок.
- Четыре типа изменений считаются по исходным VALUE, не по бакетам.
- Подключаемые пользовательские процедуры ещё не реализованы.
