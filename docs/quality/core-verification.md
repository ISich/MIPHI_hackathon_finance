# Проверка ядра — реальный прогон, не эталон жюри

Проверен commit `f269ecae51268e141609554ad5f9019df6df5481` ветки SomeShit в отдельном detached worktree; исходники не изменены, стенд не разворачивался. Установлены requirements-dev в отдельный venv, выполнен pytest: **10 passed in 0.06s**. Python: Python 3.14.9. Сеть/окружение frontend Mac этим не проверялись.

## Полный открытый набор

Команда: `python -m decision_diff.cli --before <DATASET>/RESULTS/BEFORE_MASTER --after <DATASET>/RESULTS/AFTER_BETA --out <RESULTS>`; DATASET — пакет участника RUN-20260827-0001. Значения ниже взяты из реально записанных CLI/CSV/JSON, а не из сообщения коллеги.

- Пары: 2002; missing/invalid: 0.
- Вертикальные normalized rows: 572221 (BEFORE 285698, AFTER 286523).
- Comparison rows: 289533.
- Заявки с различиями: 502.
- Смена итогового решения: 385.
- APPROVE в исходных JSON: BEFORE 657, AFTER 496.
- CLI elapsed: 14.573 секунды, полный wall time вызова 15.033 секунды на среде проверки. CLI-таймер включает нормализацию/сравнение/segments/агрегацию/экспорт; это не обещание времени на другом компьютере и не отдельный normalize+compare benchmark.

Результаты 502/385/289533 воспроизвелись. 43,8 секунды из сообщения коллеги не «ошибка»: окружения/методика различаются, его тайминг независимо не проверен.

## Дополнительная проверка результатов

Отдельный аудит без вызова функций ядра прочитал исходные решения из всех JSON, проверил их совпадение с segments и summary; проверил uniqueness normalized/comparison keys, полный outer join normalized→comparison, presence/значения/CHANGE_TYPE/DIFF_FLAG, исключения технических полей и принадлежность сменивших решение множеству changed. Для всех 44524 сохранённых fact-групп CNT совпал с независимо восстановленным distinct APP_ID. Нарушений этих инвариантов не найдено.

## Границы результата и оставшиеся задачи

Это подтверждение текущего алгоритма на открытом наборе и его внутренних инвариантов, **не** эталонная сверка организаторов и не приёмка приложения. Пять исходных checks здесь не исполнялись: product MartAPI/DuckDB/worker/UI пока не проверены. Type/numeric policy и representative-product segments требуют согласования.

Текущий pivot_facts ещё не возвращает CHANGE_TYPE как измерение, не сохраняет наружу membership и не присоединяет segments. Поэтому существующая агрегация — рабочая основа, но не полное выполнение целевого контракта BaseFacts/rollup из docs. На production-Run D2 также должен превратить skip/failed input из issues.json в явно неполный/FAILED статус по выбранной политике, а не считать exit code 0 достаточным.

## Контрольные хеши артефактов

- `comparison.csv`: `bc08e303140b408fbb8bb8a88a8afc91d18d7cfd8df44b85b94239da3b3d2dea`
- `summary.json`: `cd77ce078f7dec97c6f531681f9acb5b6ae37c52cf9b8a0270ec8f5e41a03cdd`
- `segments.csv`: `02cb79036f9848896e81af66c4fa1ce081d05a72d26c11b658b19ddf8dd1f7c6`
- `normalized_union.csv`: `fb52d36cf9a1f1f355266ad292d97cc476ef84b8dff4fb7d2b658c423f5ee892`
- `issues.json`: `4639555d872f67a4fda7ddad87fc830919588168dbc23922fe07de84f56a38ed`
- `pivot_facts.csv`: `af76b9843bf99c1686013a0ef0a6914e2856aab385d5c5444aa8bc0f12183de6`
