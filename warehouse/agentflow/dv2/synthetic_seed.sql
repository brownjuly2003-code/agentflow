-- Synthetic data seed for DV2.0 demo
-- Generates: 6 stores, 2000 customers, 800 products, 10000 orders, ~25000 line items
-- Fix: MD5() already returns FixedString(16); do NOT wrap in unhex().

-- ============ HUBS ============
-- 6 stores (master records)
INSERT INTO rv.hub_store (store_hk, store_bk, load_ts, record_source)
SELECT MD5(store_code), store_code, now64(), '1c__global'
FROM (SELECT arrayJoin(['msk-01','msk-02','spb-01','ekb-01','dxb-01','ala-01']) AS store_code);

-- 2000 customers distributed across branches
INSERT INTO rv.hub_customer (customer_hk, customer_bk, load_ts, record_source)
SELECT
    MD5(toString(number)),
    concat('CUST-', lpad(toString(number), 6, '0')),
    now64(),
    multiIf(
      number % 100 < 40, '1c__msk',
      number % 100 < 65, '1c__spb',
      number % 100 < 80, '1c__ekb',
      number % 100 < 90, '1c__dxb',
      '1c__ala'
    )
FROM numbers(2000);

-- 800 product SKUs
INSERT INTO rv.hub_product (product_hk, product_bk, load_ts, record_source)
SELECT
    MD5(sku), sku, now64(), '1c__msk'
FROM (SELECT concat('SKU-', lpad(toString(number), 5, '0')) AS sku FROM numbers(800));

-- 10000 orders
INSERT INTO rv.hub_order (order_hk, order_bk, load_ts, record_source)
SELECT
    MD5(order_id),
    order_id,
    now64(),
    multiIf(
      number % 100 < 40, '1c__msk',
      number % 100 < 65, '1c__spb',
      number % 100 < 80, '1c__ekb',
      number % 100 < 90, '1c__dxb',
      '1c__ala'
    )
FROM (
  SELECT number,
    concat(
      'bitrix__',
      multiIf(
        number % 100 < 40, 'msk',
        number % 100 < 65, 'spb',
        number % 100 < 80, 'ekb',
        number % 100 < 90, 'dxb',
        'ala'
      ),
      '__',
      lpad(toString(number), 7, '0')
    ) AS order_id
  FROM numbers(10000)
);

-- ============ LINKS ============
-- lnk_order_customer (1:1 per order, inline computation)
INSERT INTO rv.lnk_order_customer (link_hk, order_hk, customer_hk, load_ts, record_source)
SELECT
    MD5(concat(toString(number), '|', toString(cityHash64(number) % 2000))),
    MD5(concat(
      'bitrix__',
      multiIf(number % 100 < 40,'msk',number % 100 < 65,'spb',number % 100 < 80,'ekb',number % 100 < 90,'dxb','ala'),
      '__',
      lpad(toString(number), 7, '0')
    )),
    MD5(toString(cityHash64(number) % 2000)),
    now64(),
    multiIf(
      number % 100 < 40, 'bitrix__msk',
      number % 100 < 65, 'bitrix__spb',
      number % 100 < 80, 'bitrix__ekb',
      number % 100 < 90, 'bitrix__dxb',
      'bitrix__ala'
    )
FROM numbers(10000);

-- lnk_order_product (~2.5 line items per order via ARRAY JOIN range)
INSERT INTO rv.lnk_order_product (link_hk, order_hk, product_hk, load_ts, record_source)
SELECT
    MD5(concat(toString(number), '|', toString(p))),
    MD5(concat(
      'bitrix__',
      multiIf(number % 100 < 40,'msk',number % 100 < 65,'spb',number % 100 < 80,'ekb',number % 100 < 90,'dxb','ala'),
      '__',
      lpad(toString(number), 7, '0')
    )),
    MD5(concat('SKU-', lpad(toString(p), 5, '0'))),
    now64(),
    multiIf(
      number % 100 < 40, '1c__msk',
      number % 100 < 65, '1c__spb',
      number % 100 < 80, '1c__ekb',
      number % 100 < 90, '1c__dxb',
      '1c__ala'
    )
FROM numbers(10000)
ARRAY JOIN arrayMap(i -> cityHash64(number * 31 + i) % 800, range(1 + (cityHash64(number) % 4))) AS p;

-- lnk_order_store
INSERT INTO rv.lnk_order_store (link_hk, order_hk, store_hk, load_ts, record_source)
SELECT
    MD5(concat(toString(number), '|', store_code)),
    MD5(concat(
      'bitrix__',
      multiIf(number % 100 < 40,'msk',number % 100 < 65,'spb',number % 100 < 80,'ekb',number % 100 < 90,'dxb','ala'),
      '__',
      lpad(toString(number), 7, '0')
    )),
    MD5(store_code),
    now64(),
    '1c__global'
FROM (
  SELECT number,
    multiIf(
      number % 100 < 40, if(number % 2 = 0, 'msk-01', 'msk-02'),
      number % 100 < 65, 'spb-01',
      number % 100 < 80, 'ekb-01',
      number % 100 < 90, 'dxb-01',
      'ala-01'
    ) AS store_code
  FROM numbers(10000)
);
