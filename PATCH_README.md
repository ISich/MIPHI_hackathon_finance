# D1 + D4: аналитический слой (патч только новых файлов)

Не распаковывайте поверх чужих изменений без проверки. Добавьте файлы, сохраняя структуру каталогов, в корень MIPHI_hackathon_finance. НЕ заменяйте существующие core.py, configs.py, cli.py, segments.py, reporting.py, pyproject.toml, requirements, docs, frontend или API.

## Зависимость
В существующем pyproject.toml в [project] добавьте `dependencies = ["duckdb>=1.1,<2"]` (если уже существует `dependencies`, просто добавьте duckdb в список, без дублирования ключа). Установите: `python -m pip install -e ".[dev]"` либо `python -m pip install duckdb` для проверки.

## Тесты
`python -m pytest -v`
Проверьте, что интеграционный тест DuckDB не SKIPPED.

## Использовать уже существующий полный прогон
```powershell
python -m decision_diff.analytics_cli `
  --data outputs/full_run `
  --checks checks `
  --db outputs/full_run/mart.duckdb
```
Перезапуск импорта с `--replace`; предварительно закройте активные подключения к DuckDB.

## Результат
Создаст `outputs/full_run/mart.duckdb` и `outputs/full_run/checks_report.json`. `FAIL` в строке проверки — бизнес-результат, ошибки исполнения — в `diagnostics`.

## Границы D1/D4
`storage.py` импортирует CSV завершённого прогона, `mart.py` предоставляет MartAPI и drill-down запросы, `check_runner.py` выполняет доверенные проверки; пользовательский произвольный код из веб-редактора пока НЕ изолирован (должен вызываться runner-ом D2 в отдельном ограниченном процессе/контейнере).

Включённые `checks/` — открытые файлы организаторов, без изменения логики.

## Ограничения
Сейчас связь counts -> APP_ID вычисляется запросом, а не хранится отдельной materialized membership-таблицей. Уточните DTO `docs/` с D2 и D3. Код PR #1 пока не сверялся: нет доступа к содержимому.
