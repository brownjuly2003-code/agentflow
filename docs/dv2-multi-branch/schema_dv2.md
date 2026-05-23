# DV2.0 Schema — Hub/Link/Sat Shortlist для AgentFlow extension

## Контекст

Multi-source / multi-branch e-com одежды/обуви. 5 локаций (MSK / SPB / EKB / DXB / ALA). Источники: 1С (УТ), Битрикс24, Excel-логистика, XML-обмен сайта, API маркетплейсов (ВБ/Озон).

Naming convention взяты с реальных данных X5 Retail Hero, Lenta BigTarget и Магнит engineering blog (см. `kimi_magnit_research.md`). DDL-шаблоны — адаптация Celestinfo + Tampere DV2.0 automation patterns под ClickHouse.

## Naming conventions

- `hub_<entity>` — хабы
- `lnk_<entity_a>_<entity_b>` — связи
- `sat_<entity>_<facet>__<source>__<branch>` — сателлиты, **композитный suffix** разделяет источник и юрисдикцию
- `*_hk` — hash key (FixedString(16), MD5 от business key)
- `*_bk` — business key (raw String)
- `load_ts` — DateTime64(3), момент загрузки в warehouse
- `hash_diff` — FixedString(16), MD5 от всех бизнес-атрибутов satellite, для idempotent CDC
- `record_source` — LowCardinality(String), формат `{source_system}__{branch_code}`, всегда заполнен

## Hub-список (8 ядер)

| Hub | Business key | Источники | Branch-context | Комментарий |
|---|---|---|---|---|
| `hub_customer` | `customer_id` (canonical после dedup по email/phone) | 1С, Битрикс, сайт, ВБ-API, Озон-API | per-branch sats | один клиент = одна запись в hub, представления — в satellites |
| `hub_product` | `sku` (canonical) | 1С, WMS, сайт, маркетплейсы | global | артикул как единая бизнес-ключ; маркировка через отдельный hub |
| `hub_order` | `order_id` композитный `{source}__{local_id}` | 1С, Битрикс, сайт, маркетплейсы | per-branch sats | ordr-id не уникален между каналами, поэтому композит |
| `hub_shipment` | `shipment_id` | WMS, Excel-логистика | per-branch | физическая отгрузка |
| `hub_store` | `store_code` (`msk-01`, `spb-shr-02`, `dxb-01`, `ala-01`) | 1С-справочник | global | **новый по сравнению с предыдущим списком** — критично для multi-branch attribution |
| `hub_supplier` | `supplier_inn` (или иностр. tax-id) | 1С | global | поставщик может работать с несколькими филиалами |
| `hub_employee` | `employee_id` | 1С-ЗУП, Битрикс | per-branch sats | продавец/менеджер для sales attribution |
| `hub_marking_code` | `gs1_gtin` | 1С, WMS | global | Честный Знак коды |

## Link-список

| Link | Endpoints | Cardinality | Why |
|---|---|---|---|
| `lnk_order_customer` | order × customer | M:1 | классика |
| `lnk_order_product` | order × product (с qty/price на самой связи через effectivity sat) | M:N | line items |
| `lnk_order_store` | order × store | M:1 | какой филиал выполнил |
| `lnk_order_employee` | order × employee | M:1 | sales attribution |
| `lnk_order_shipment` | order × shipment | M:N (split-shipments) | один заказ может ехать несколькими отгрузками |
| `lnk_shipment_store` | shipment × store (origin/destination) | M:1 each | склад отправки и получения |
| `lnk_product_supplier` | product × supplier | M:N + effectivity | один SKU может закупаться у нескольких поставщиков |
| `lnk_product_marking` | product × marking_code | 1:N | один SKU → много экземпляров с уникальными GTIN |

## Satellite-стратегия

### Принцип per-source × per-branch

Каждый сателлит имеет **двойной квалификатор**: источник + филиал. Это позволяет:
- хранить per-jurisdiction PII раздельно (РФ-данные не пересекают границу)
- разрешать конфликты между источниками (1С vs Битрикс) на уровне Business Vault, не теряя raw
- держать audit-trail per filiation

### Примеры satellites вокруг `hub_customer`

| Satellite | record_source | Какие атрибуты | Hot/Cold |
|---|---|---|---|
| `sat_customer_personal__1c__msk` | `1c__msk` | ФИО, email, phone, дата рождения | HOT (PII, остаётся в РФ) |
| `sat_customer_personal__1c__dxb` | `1c__dxb` | то же, по DXB-резидентам | HOT (PII, остаётся в ОАЭ) |
| `sat_customer_loyalty__bitrix__msk` | `bitrix__msk` | сегмент, баллы, last_visit | HOT |
| `sat_customer_behavior__site__msk` | `site__msk` | cart events, view events (агрегаты) | HOT, реплицируется в cold anonymized |
| `sat_customer_anon__msk` | `1c__msk` (derived) | age_bucket, geo_region, segment — БЕЗ direct PII | COLD (parquet в cloud) |

### Примеры satellites вокруг `hub_order`

| Satellite | record_source | Атрибуты | SCD2? |
|---|---|---|---|
| `sat_order_header__bitrix__msk` | `bitrix__msk` | order_date, channel, status, total | да, статусы меняются |
| `sat_order_pricing__1c__msk` | `1c__msk` | subtotal, discount, tax, shipping_cost | да, при пересчётах |
| `sat_order_marketplace__wb__msk` | `wb__msk` | wb_status, wb_commission, return_window | да, возвраты |

### Примеры satellites вокруг `hub_product`

| Satellite | record_source | Атрибуты | SCD2? |
|---|---|---|---|
| `sat_product_catalog__1c__msk` | `1c__msk` | name, brand, category, size, color, ТНВЭД | да, ребрендинг |
| `sat_product_price__1c__msk` | `1c__msk` | retail_price, wholesale_price, currency, valid_from | **очень активный SCD2**, прайс-лист пересчитывается ежедневно |
| `sat_product_stock__wms__msk` | `wms__msk` | qty_on_hand, qty_reserved, qty_available | да, постоянно |
| `sat_product_marketplace__wb__msk` | `wb__msk` | wb_id, wb_price, wb_status, wb_rating | да |

## Sample DDL (ClickHouse)

```sql
-- Hub
CREATE TABLE rv.hub_customer (
    customer_hk     FixedString(16),
    customer_bk     String,
    load_ts         DateTime64(3),
    record_source   LowCardinality(String),
    INDEX idx_bk customer_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (customer_hk);

-- Satellite (hot, with PII)
CREATE TABLE rv.sat_customer_personal__1c__msk (
    customer_hk     FixedString(16),
    load_ts         DateTime64(3),
    hash_diff       FixedString(16),
    record_source   LowCardinality(String) DEFAULT '1c__msk',
    first_name      String,
    last_name       String,
    email           String,
    phone           String,
    birth_date      Nullable(Date),
    pii_flag        Bool DEFAULT true
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (customer_hk, load_ts);

-- Link
CREATE TABLE rv.lnk_order_customer (
    link_hk         FixedString(16),  -- MD5(order_hk || customer_hk)
    order_hk        FixedString(16),
    customer_hk     FixedString(16),
    load_ts         DateTime64(3),
    record_source   LowCardinality(String)
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (link_hk);

-- Effectivity satellite на line items (qty/price живут на связи, не на хабе)
CREATE TABLE rv.sat_lnk_order_product__1c__msk (
    link_hk         FixedString(16),
    load_ts         DateTime64(3),
    hash_diff       FixedString(16),
    record_source   LowCardinality(String) DEFAULT '1c__msk',
    qty             Decimal(18, 3),
    unit_price      Decimal(18, 2),
    discount_pct    Decimal(5, 2),
    line_total      Decimal(18, 2)
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (link_hk, load_ts);
```

## Anonymization layer (hot → cold)

Перед offload в cloud cold tier (HF Datasets / Backblaze B2) проходит **transform-step**:

```sql
-- AgentFlow CronJob, daily/weekly
INSERT INTO rv_cold.sat_customer_anon__msk
SELECT
    customer_hk,                                    -- хеш остаётся, mapping в hot
    load_ts,
    multiIf(age < 25, '18-24', age < 35, '25-34',
            age < 45, '35-44', age < 55, '45-54', '55+')  AS age_bucket,
    -- ФИО, email, phone, birth_date УБРАНЫ
    geoToRegion(geo_lat, geo_lon)                   AS geo_region,
    customer_segment,
    hash_diff
FROM rv.sat_customer_personal__1c__msk
WHERE load_ts < now() - INTERVAL 12 MONTH;
```

Cold-сторона **не имеет mapping `customer_hk → email/phone`** — это знание остаётся только в hot Postgres on-prem. Restore identity возможен только через rehydration via on-prem hub.

## Source loading order (для AgentFlow Argo Workflow)

```
1. Hubs (parallel: customer, product, order, store, supplier, employee, marking, shipment)
   ↓
2. Links (parallel: order_customer, order_product, order_store, ...)
   ↓
3. Satellites (parallel by source × branch — full fan-out)
   ↓
4. Business Vault (computed marts, point-in-time, bridges) — depends on hot satellites
   ↓
5. Cold offload (daily/weekly) — anonymized parquet → S3-compatible
```

Idempotent re-loading через `hash_diff` — если satellite-payload не изменился, no-op insert.

## Что ещё в шорт-листе на ближайший спринт

- **Бизнес-vault слой:** `bv_customer_mdm` (golden record с priority rules: 1С → master для PII, Битрикс → master для loyalty), `bv_order_canonical` (унифицированный статусный поток между channel'ами)
- **Reference tables:** календарь, валюты, ТНВЭД-коды (для возможности join'ов без отдельных хабов)
- **PIT tables:** для критичных pull-запросов с фиксированной датой
- **Effectivity satellites:** open/close intervals для SCD2-tracking на links

## Связь с реальными source-data

| Hub/Sat | Прототип-данные | Where to get |
|---|---|---|
| `hub_customer` + `sat_customer_personal__*` | X5 Retail Hero `clients.csv` | Kaggle |
| `hub_product` + `sat_product_catalog__*` | X5 Retail Hero `products.csv` | Kaggle |
| `lnk_order_customer` + `sat_lnk_order_product__*` | X5 Retail Hero `purchases.csv` (45.8 млн строк) | Kaggle |
| `sat_customer_loyalty__*` | Lenta BigTarget loyalty features | Kaggle |
| `sat_order_marketplace__wb__*` | Synthesize from public ВБ API docs | Wildberries |
| `hub_marking_code` | Честный Знак GS1 examples | crpt.ru |

Для PoC демо тащим X5 Retail Hero (45М транзакций) в ClickHouse через AgentFlow Argo Workflow, маппим в DV2.0 hub/link/sat, добавляем synthetic branches (привязка к store_id из X5 → искусственно распределяем по 5 локациям).
