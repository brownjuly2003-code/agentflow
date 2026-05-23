# Задача: найти куски реальных данных/схем Магнит (или X5/Лента) для DV2.0 моделирования

## Контекст

Строим DV2.0 hub/link/sat шорт-лист для портфолио-кейса. Легенда — mid-market fashion e-com, но **детали из реального крупного retail (Магнит первый приоритет)** помогут построить hub-keys, satellite attributes и naming-conventions ближе к индустриальной реальности. Новизна не критична — 2020-2026 OK.

## Что искать

1. **Публичные SQL-схемы / ER-диаграммы** из engineering blog'ов Магнита, X5 Retail Group, Ленты, Перекрёстка, Пятёрочки. Особенно интересно:
   - product hierarchy (категории, SKU, штрих-коды, единицы измерения)
   - customer/loyalty схема (карты лояльности, привилегии, transactions)
   - inventory/остатки (multi-store, multi-warehouse)
   - promotions/акции
   - возвраты

2. **Kaggle / data.world / open data датасеты** с настоящими данными ритейлера:
   - Magnit / X5 / Lenta open competition datasets
   - Российские retail open data (Минпромторг? FAS?)
   - Анонимизированные transaction logs от ритейлеров

3. **Habr-статьи с code samples** или фрагментами схемы:
   - https://habr.com/ru/companies/magnit/
   - https://habr.com/ru/companies/x5/
   - https://habr.com/ru/hubs/data_warehouse/

4. **GitHub-репозитории** с примерами таблиц:
   - Магнит / X5 в GitHub поиске
   - dbt-проекты для retail
   - DV2.0 примеры для retail (русско- и англоязычные)

5. **Conference talks** (Highload, Datafest, ClickHouse Meetup, dbt Coalesce) с кусками реальной схемы Магнит/X5

## Формат вывода

Для каждой находки:
```
1. [Title]
   URL: ...
   Что там есть: схема SQL / CSV-данные / SQL-фрагменты / ER-диаграмма / другое
   Reusable для DV2.0: да/нет/частично — пояснение что именно можно взять
   Цитата/пример: [короткий пример если есть]
```

Минимум 5 находок. Если по Магниту сухо — пускай по X5, Ленте, Перекрёстку. Если по российским сухо — иностранные retail (Walmart, Target, Carrefour open data) — но это уже plan B, приоритет на РФ.

Output на русском, цитаты на языке источника. Не галлюцинировать URL — если кейс не публикован, написать «не нашёл».
