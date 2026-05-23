Ниже — подборка из **7 находок**, отранжированных по полезности для DV2.0-моделирования. Приоритет отдан реальным российским ритейлерам (X5, Лента, Магнит); иностранные источники использованы только как DDL-шаблоны.

---

### 1. X5 Retail Hero — Uplift Modeling Dataset (Kaggle)
**URL:** https://www.kaggle.com/datasets/shonenkov/x5retailheroupliftrawdata  
**Что там есть:** Реальные CSV-данные X5 Retail Group (Пятёрочка, Перекрёсток, Карусель):  
- `clients.csv` — ~400 K анонимизированных клиентов (демография, дата регистрации);  
- `purchases.csv` — ~45.8 M строк транзакций (client_id, transaction_id, timestamp, store_id, product_id, quantity, price);  
- `products.csv` — справочник товаров с иерархией категорий;  
- `uplift_train/test.csv` — флаги коммуникации и покупки (treatment / target).  
**Reusable для DV2.0:** Да — полноценный набор для построения **Hub_Customer**, **Hub_Product**, **Hub_Store**, **Link_Transaction**, **Sat_Customer_Demo**, **Sat_Product_Category**, **Sat_Transaction_Detail**. Естественные business keys: `client_id`, `product_id`, `transaction_id`.  
**Цитата/пример:**  
```csv
client_id,transaction_id,transaction_datetime,product_id,product_quantity,trn_sum_from_iss
008fb49e3a,1234567890,2019-01-15 08:23:11,100500,2,158.50
```

---

### 2. Lenta — BigTarget Uplift Dataset (Kaggle / Hackathon 2020)
**URL:** https://www.kaggle.com/datasets/mrmorj/bigtarget  
**Что там есть:** CSV-данные ритейлера Лента (~687 K пользователей, ~196 признаков). Ключевые поля: `CardHolder` (customer id), `gender`, `age`, `main_format` (1 — продуктовый, 0 — гипермаркет), `cheque_count_3m_g34` (чеки по группам за 3 мес), `sale_sum_6m_g*`, `disc_sum_6m_g*`, `crazy_purchases_*`, `response_att` (визит), `group` (treatment/control).  
**Reusable для DV2.0:** Да — показывает реальные **naming conventions** лояльности/транзакций Ленты: `cheque_count`, `sale_sum`, `disc_sum`, `main_format`, `response_att`. Можно использовать как прототип Satellite-атрибутов вокруг Hub_Customer (периодичность 15d/1m/3m/6m/12m, иерархия товарных групп g*).  
**Цитата/пример:**  
```csv
CardHolder,gender,age,main_format,cheque_count_3m_g34,sale_sum_6m_g34,response_att,group
A12B34C56,F,34.0,1,12,5400.0,1,treatment
```

---

### 3. Highload-оптимизация 1С на примере «Магнита» (Infostart)
**URL:** https://infostart.ru/1c/articles/1357723/  
**Что там есть:** Фрагменты реальной 1С-схемы (MS SQL Server), используемой в «Магните» и «Аптеки Магнит». Автор разбирает оптимизацию типового запроса «Отчёт о розничных продажах» УТ11. Упоминаются таблицы: `ЧекиККМ` (POS-чеки), `ЧекиККМ.Серии` (партии/серии в чеке), временные таблицы с составными типами, регистры с «десятками миллионов записей».  
**Reusable для DV2.0:** Частично — не ER-диаграмма целиком, но подтверждает реальные entity names ритейла Магнита: **ЧекККМ** (факт продажи), **Серии** (batch/lot tracking), **Номенклатура**, **Контрагенты**. Полезно для именования Hub/Satellite (например, Hub_POS_Transaction, Sat_Transaction_Batch).  
**Цитата/пример:**  
> «Этот запрос выполнялся 28 секунд, хотя в самой табличной части Серий содержалось всего несколько сотен записей — ерунда. ... в этой табличной части несколько десятков миллионов записей.»

---

### 4. Архитектура данных «Магнит Маркета» (Habr + Mindbox)
**URL:** https://habr.com/ru/companies/magnit/articles/823268/ и https://mindbox.ru/journal/cases/magnit-dostavka/  
**Что там есть:** Описание data-интеграции e-com Магнита. Упрощённая схема потоков данных: **Bitrix** (мастер-БД клиентов/заказов) → **CDP Mindbox**; **Магнит ID** (единое хранилище персональных данных лояльности); **Kafka** (топики Shops, EMS, Collect); **DWH** (накопление статистики коммуникаций). Сущности: client, order, cart, product_view, push, store, delivery_zone, order_status, fraud_flag.  
**Reusable для DV2.0:** Частично — нет SQL-DDL, но даёт **реальные business entities и naming conventions** для fashion/e-com: `client_id`, `order_id`, `cart_id`, `product_sku`, `store_id`, `delivery_zone`, `order_status`, `push_id`. Можно использовать как основу для Hub/Link-списка.  
**Цитата/пример:**  
> «Магнит ID — единое хранилище персональных данных, которое объединяет информацию изо всех приложений «Магнита»: «Магнит Доставка», «Магнит Скидки», «Мой Магнит» с программой лояльности в рознице.»

---

### 5. Data Vault 2.0 DDL Patterns для Retail (Celestinfo + dbtvault)
**URL:** https://www.celestinfo.com/data-vault-modeling-guide.html  
**Что там есть:** Готовые SQL-фрагменты CREATE TABLE под DV2.0 на примере sales-системы (customer, product, order). Примеры: `raw_vault.sat_customer_crm`, `Hub_Customer` (business key `customer_id`), `Hub_Product` (`product_sku`), `Link_Order`, `Sat_Product_Catalog`, `Sat_Order_Details`. Все таблицы с техническими колонками: `*_hk` (hash key), `load_ts`, `hash_diff`, `record_source`.  
**Reusable для DV2.0:** Да — **готовые DDL-шаблоны**, которые можно напрямую адаптировать под данные X5/Ленты. Показывает naming convention (`hub_`, `lnk_`, `sat_`, `_hk`, `_ldts`, `hash_diff`).  
**Цитата/пример:**  
```sql
CREATE TABLE raw_vault.sat_customer_crm (
    customer_hk     BINARY(16)    NOT NULL,
    load_ts         TIMESTAMP_NTZ NOT NULL,
    hash_diff       BINARY(16)    NOT NULL,
    customer_name   VARCHAR(200),
    email           VARCHAR(200),
    phone           VARCHAR(50),
    record_source   VARCHAR(100)  NOT NULL,
    CONSTRAINT pk_sat_customer_crm PRIMARY KEY (customer_hk, load_ts)
);
```

---

### 6. Автоматизация DV2.0 на T-SQL (Tampere University + GitHub)
**URL:** https://trepo.tuni.fi/bitstream/10024/123026/2/LaukkanenJenni.pdf  
**Что там есть:** Магистерская работа с полным циклом автоматического преобразования реляционной схемы в DV2.0. ER-диаграмма **Adventure Works** в нотации DV (Hubs — синие, Links — зелёные, Satellites — жёлтые). Описаны Reference tables (календари, справочники), Effectivity Satellites, Bridge, PIT. T-SQL код для генерации hash keys и load patterns.  
**Reusable для DV2.0:** Да — демонстрирует, как типовую retail-схему (Product, Customer, Order, Category) переложить в Hub-Link-Satellite. Полезно для моделирования **product hierarchy** и **multi-source customer data**.  
**Цитата/пример:**  
> «The standalone tables in the model, which do not contain any foreign keys, consist only of a hub and an associated satellite... If the table has a relation to itself, i.e., the table contains a business key and a foreign key with the same values, for example in a hierarchical situation, a hub, satellite and link table are created.»

---

### 7. dbt Retail POC — Customer / Item / Order Schema (PopSQL)
**URL:** https://popsql.com/blog/dbt-models  
**Что там есть:** Пример dbt-моделей для розничной компании. Базовые таблицы (staging): `Customer` (`customer_id`, `first_name`, `last_name`, `email_address`, ...), `Item order` (`item_id`, `quantity`, `price`, `description`), и производная модель `order` с JOIN, агрегацией `SUM(total_price)` и генерацией `order_id` через `MD5(customer_id, order_date, total_price)`.  
**Reusable для DV2.0:** Частично — это **not DV2.0**, но демонстрирует типичную retail-нормализацию, которую затем можно переложить в DV. Полезен список атрибутов для Satellite (name, address, email, quantity, price, description).  
**Цитата/пример:**  
```sql
WITH individual_orders AS (
   SELECT
       c.customer_id,
       i.item_id,
       CURRENT_TIMESTAMP() as order_date,
       SAFE_MULTIPLY(i.quantity, i.price) as total_price
   FROM customers c
   INNER JOIN item_orders i ON c.customer_id = i.customer_id
)
SELECT MD5(customer_id, order_date, total_price) as order_id, * FROM aggregated_orders;
```

---

### Итоговая сводка
| # | Источник | Тип | Приоритет для DV2.0 |
|---|----------|-----|---------------------|
| 1 | X5 Retail Hero (Kaggle) | CSV-данные | 🔥 Высокий — реальные transaction logs |
| 2 | Lenta BigTarget (Kaggle) | CSV-данные | 🔥 Высокий — реальная loyalty схема |
| 3 | Infostart: 1С Магнит | SQL-фрагменты | Средний — реальные table names Магнита |
| 4 | Habr: Магнит Маркет | Архитектурная схема | Средний — entities и naming conventions |
| 5 | Celestinfo DV2.0 DDL | SQL-шаблоны | 🔥 Высокий — готовые CREATE TABLE |
| 6 | Tampere Univ. DV Auto | ER + T-SQL | Высокий — методология retail→DV2.0 |
| 7 | PopSQL dbt Retail | dbt/SQL пример | Средний — базовая retail нормализация |

**Рекомендация:** взять **business keys и атрибуты** из датасетов X5 и Ленты, **naming conventions** из статей про Магнит, а **DDL-шаблоны** — из Celestinfo / Tampere, чтобы собрать реалистичный DV2.0 short-list.
