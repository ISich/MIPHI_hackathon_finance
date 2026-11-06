# Контракт данных v0 — стык D1/D2/D4

**Статус:** логические поля C из PRD §6–8; физическое хранение и расширения A/Q. Steward D1 для rows, D4 для facts, D2 для physical schema. До параллельного production-кода все три владельца подтверждают совместимость.

## Слои, ключи, consumers

| Слой | Одна строка | Ключ внутри Run | Consumer |
|---|---|---|---|
| normalized | существующий лист одного среза | SOURCE+APP_ID+PATH+ARRAY_KEY | compare, facts |
| comparison | одна пара атрибутов | APP_ID+PATH+ARRAY_KEY | MartAPI, детали |
| segments | заявка | APP_ID | checks, фильтры |
| base facts | фиксированная базовая группа после сравнения | data revision + fact_id | server pivot rollup |
| base membership | принадлежность заявки базовому факту | fact_id + APP_ID | distinct totals, drill-down |

Нормализованный технический UNION вертикальный. Comparison — представление пары для MartAPI; физическая материализация pending PRD Q2. Run/owner scope добавляет платформа, не пользовательский JSON.

### normalized

APP_ID, SOURCE (`BEFORE`/`AFTER`), PREFIX, CLASS, SUFFIX, ARRAY_KEY, KEY, PATH, VALUE, ADJUSTED_VALUE. На каждый leaf один экземпляр в срезе; excluded fields отсутствуют в сравниваемом наборе. Внешний VALUE строковый, внутренние presence/type metadata — явное расширение. Типовая/числовая политика pending Q5, должна быть одинаковой во всех producers.

### comparison — точный внешний формат

APP_ID, PREFIX, CLASS, SUFFIX, ARRAY_KEY, KEY, PATH, VALUE_BEFORE, VALUE_AFTER, ADJUSTED_BEFORE, ADJUSTED_AFTER, DIFF_FLAG (0/1), CHANGE_TYPE (`SAME`, `VALUE_CHANGED`, `ATTRIBUTE_NEW`, `ATTRIBUTE_LOST`). DIFF_FLAG=0 только при SAME. Unique по логическому ключу; не дублировать пару для SOURCE. Внешняя отсутствующая сторона представляется пустой строкой `""` по S4. Настоящая пустая строка тоже может отображаться как `""`, но наличие определяется CHANGE_TYPE и отдельным presence metadata, не display-текстом. Missing не равен JSON null (`"NULL"`). Фильтры MartAPI value_before/value_after — точное совпадение внешнего значения: `""` может выбрать и missing, и настоящий пустой VALUE; для структурного различения дополнительно фильтровать change_type. Новую семантику presence-фильтра не добавлять молча в выданный MartAPI.

### segments

APP_ID; DECISION_BEFORE/AFTER; DECISION_CHANGED; PRODUCTS; TOP_OFFER_BEFORE/AFTER; PARTNER_TYPE; ROUTING_METHOD; PD_MODEL_BEFORE/AFTER; CUTOFF_BEFORE/AFTER; REJECT_REASON_BEFORE/AFTER; SCORE_OKB_BEFORE/AFTER. PRODUCTS — строка продуктов через `;`; выбор product_id или product_name требует единой политики D1/D4 (см. implementation-status: существующее ядро использует name с fallback ID, тогда как PRD предлагает ID). DECISION_CHANGED bool/int 0/1. Несколько продуктов не размножают segments. Multi-value projection, TOP_OFFER и исходные политики заданы процедурой с учётом открытого Q5, не случайным порядком массива.

### Два уровня facts/membership — предложение команды

**Уровень 1, AGGREGATING, до выбора раскладки:** заменяемая aggregate-процедура получает normalized vertical rows, comparison projection и segments и возвращает `BaseFacts` + `BaseMembership` + диагностики/метаданные схемы. Для каждого существующего normalized leaf взять SOURCE и ADJUSTED_VALUE этого среза, присоединить DIFF_FLAG/CHANGE_TYPE из comparison по APP_ID/PATH/ARRAY_KEY и application segments. Отсутствующую сторону NEW/LOST не синтезировать.

Фиксированная базовая детализация: PREFIX, CLASS, SUFFIX, PATH, ARRAY_KEY, KEY, VALUE_ADJUSTED (ADJUSTED_VALUE соответствующего SOURCE), SOURCE, DIFF_FLAG, CHANGE_TYPE и согласованные поля segments. Строка BaseFacts: fact_id, перечисленные dimension fields, CNT, membership_ref; data revision задаётся метаданными артефакта. BaseMembership: fact_id + APP_ID, без дублей. `CNT = COUNT(DISTINCT APP_ID)` соответствующего membership. Multi-value segments требуют явной согласованной политики: expansion, если выбран, не меняет distinct-знаменатель. Это выход подготовки фактов, не пользовательская pivot-раскладка.

**Уровень 2, запрос сводной после финализации:** D4 server rollup фильтрует BaseFacts и группирует выбранные измерения. Cell count/totals — cardinality объединения BaseMembership для подходящих базовых фактов. Не SUM(CNT) на пересекающихся группах. Raw JSON заново не разбирается; сводная действительно питается предварительно подготовленными counts и связями APP_ID.

Group locator — opaque ссылка на Run/data revision + канонический фильтр/раскладку/координаты ячейки, а **не ключ BaseFact**. D4 формирует locator, D3 передаёт его неизменным, D2 контролирует owner scope. Пагинация union membership возвращает элементы и полный distinct total; total не длина текущей страницы. При out-of-range — пустая страница с прежним total, не новый итог 0.

## Инварианты и граничные фикстуры

Четыре CHANGE_TYPE разбивают comparison; changed-apps≤total-apps. При включённом decision path смена решения входит в множество changed. Отдельные тесты: два products у заявки; два models с общим feature; rule ARRAY_KEY `<product_id>|<rule_name>`; composite offer key; key-array reorder; positional vector; изменение внутри бакета; missing/null/empty. Числа публичного демо и inconsistent README не заменяют официальный baseline.

## Приёмка стыка

D1 отдаёт маленькую настоящую fixture и schema-valid expected. D4 обязан успешно прочитать её MartAPI и получить ожидаемое срабатывание исходного check. D2 сохраняет/читает без преобразования типов `0`→`"0"` или `true`→`True`. Изменение схемы требует reviewer producer+consumer и обновления fixtures; не заводить несовместимые DTO в каждом модуле.
