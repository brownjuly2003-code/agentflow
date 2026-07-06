-- Synthetic data seed for DV2.0 demo — own-brand kitchen-appliance importer
-- legend (docs/domain.md, docs/generator-spec.md). Numbers mirror
-- warehouse/agentflow/dv2/reference/legend.py so the seed and the §12
-- invariant tests can't silently drift apart.
--
-- Customer numbering (hub_customer, 2,500 = 2,000 retail + 500 dealers,
-- generator-spec.md §7/§11): contiguous bands, not modulo slicing.
--   0..1999      retail (msk jurisdiction only)      record_source 1c__msk
--   2000..2189   dealer msk (190)                     record_source 1c__msk
--   2190..2289   dealer spb (100)                      record_source 1c__spb
--   2290..2359   dealer ekb (70)                        record_source 1c__ekb
--   2360..2419   dealer dxb (60)                        record_source 1c__dxb
--   2420..2499   dealer ala (80)                        record_source 1c__ala
--
-- Order numbering (hub_order, 10,000 ≈ 5.1 baseline days, §11):
--   0..8899      marketplace (8,900)     record_source mp__msk
--   8900..9179   D2C site (280)          record_source site__msk
--   9180..9539   B2B msk (360)           record_source bitrix__msk
--   9540..9719   B2B spb (180)           record_source bitrix__spb
--   9720..9849   B2B ekb (130)           record_source bitrix__ekb
--   9850..9924   B2B dxb (75)            record_source bitrix__dxb
--   9925..9999   B2B ala (75)            record_source bitrix__ala
--
-- Fix (kept from the original seed): MD5() already returns FixedString(16);
-- do NOT wrap in unhex().

-- ============ HUBS ============
-- 6 stores (master records) — footprint unchanged (domain.md §1).
INSERT INTO rv.hub_store (store_hk, store_bk, load_ts, record_source)
SELECT MD5(store_code), store_code, now64(), '1c__global'
FROM (SELECT arrayJoin(['msk-01','msk-02','spb-01','ekb-01','dxb-01','ala-01']) AS store_code);

-- 2,500 customers: 2,000 retail (msk) + 500 dealers banded by branch.
INSERT INTO rv.hub_customer (customer_hk, customer_bk, load_ts, record_source)
SELECT
    MD5(toString(number)),
    concat('CUST-', lpad(toString(number), 6, '0')),
    now64(),
    multiIf(
      number < 2190, '1c__msk',
      number < 2290, '1c__spb',
      number < 2360, '1c__ekb',
      number < 2420, '1c__dxb',
      '1c__ala'
    )
FROM numbers(2500);

-- 160 kitchen-appliance SKUs (generator-spec.md §3), centrally managed catalog.
INSERT INTO rv.hub_product (product_hk, product_bk, load_ts, record_source)
SELECT
    MD5(sku), sku, now64(), '1c__msk'
FROM (SELECT concat('SKU-', lpad(toString(number), 5, '0')) AS sku FROM numbers(160));

-- 10,000 orders: 8,900 marketplace + 280 D2C site + 820 B2B (per-branch
-- msk 360 / spb 180 / ekb 130 / dxb 75 / ala 75).
INSERT INTO rv.hub_order (order_hk, order_bk, load_ts, record_source)
SELECT MD5(order_bk), order_bk, now64(), record_source
FROM (
  SELECT
    number,
    multiIf(
      number < 8900, 'mp__msk',
      number < 9180, 'site__msk',
      number < 9540, 'bitrix__msk',
      number < 9720, 'bitrix__spb',
      number < 9850, 'bitrix__ekb',
      number < 9925, 'bitrix__dxb',
      'bitrix__ala'
    ) AS record_source,
    concat(record_source, '__', lpad(toString(number), 7, '0')) AS order_bk
  FROM numbers(10000)
);

-- 160 SKU-level GS1/Chestny Znak marking-code templates (one per product,
-- 'issued' — a template registration used repeatedly, not a per-unit scan
-- state) + ~12,000 per-unit code sample (≈ one container), status split
-- issued 25% / in_circulation 60% / withdrawn 15% (§11).
INSERT INTO rv.hub_marking_code (marking_code_hk, marking_code_bk, load_ts, record_source)
SELECT MD5(marking_code_bk), marking_code_bk, now64(), record_source
FROM (
  SELECT concat('CZ-SKU-', lpad(toString(number), 5, '0')) AS marking_code_bk, '1c__global' AS record_source
  FROM numbers(160)
  UNION ALL
  SELECT
    concat('CZU-', lpad(toString(number % 160), 5, '0'), '-', lpad(toString(intDiv(number, 160)), 7, '0')) AS marking_code_bk,
    '1c__global' AS record_source
  FROM numbers(12000)
);

-- ============ LINKS ============
-- lnk_order_customer: marketplace/site orders draw from the retail pool;
-- B2B orders draw from the dealer pool of their own branch.
INSERT INTO rv.lnk_order_customer (link_hk, order_hk, customer_hk, load_ts, record_source)
SELECT
    MD5(concat(order_bk, '|', toString(customer_number))),
    MD5(order_bk),
    MD5(toString(customer_number)),
    now64(),
    record_source
FROM (
  SELECT
    number,
    multiIf(
      number < 8900, 'mp__msk',
      number < 9180, 'site__msk',
      number < 9540, 'bitrix__msk',
      number < 9720, 'bitrix__spb',
      number < 9850, 'bitrix__ekb',
      number < 9925, 'bitrix__dxb',
      'bitrix__ala'
    ) AS record_source,
    concat(record_source, '__', lpad(toString(number), 7, '0')) AS order_bk,
    multiIf(
      number < 9180, cityHash64(number) % 2000,                    -- mp/site -> retail [0,2000)
      number < 9540, 2000 + (cityHash64(number) % 190),             -- B2B msk -> dealer [2000,2190)
      number < 9720, 2190 + (cityHash64(number) % 100),             -- B2B spb -> dealer [2190,2290)
      number < 9850, 2290 + (cityHash64(number) % 70),              -- B2B ekb -> dealer [2290,2360)
      number < 9925, 2360 + (cityHash64(number) % 60),              -- B2B dxb -> dealer [2360,2420)
      2420 + (cityHash64(number) % 80)                              -- B2B ala -> dealer [2420,2500)
    ) AS customer_number
  FROM numbers(10000)
);

-- lnk_order_product: line-count and product mix follow order shapes (§2).
-- Marketplace/D2C lean toward the ABC bestseller band (top 24 SKUs, §3);
-- B2B picks uniformly across the full 160-SKU catalog.
INSERT INTO rv.lnk_order_product (link_hk, order_hk, product_hk, load_ts, record_source)
SELECT
    MD5(concat(order_bk, '|', toString(p))),
    MD5(order_bk),
    MD5(concat('SKU-', lpad(toString(p), 5, '0'))),
    now64(),
    '1c__msk'
FROM (
  SELECT
    number,
    concat(
      multiIf(
        number < 8900, 'mp__msk',
        number < 9180, 'site__msk',
        number < 9540, 'bitrix__msk',
        number < 9720, 'bitrix__spb',
        number < 9850, 'bitrix__ekb',
        number < 9925, 'bitrix__dxb',
        'bitrix__ala'
      ),
      '__',
      lpad(toString(number), 7, '0')
    ) AS order_bk,
    multiIf(
      number < 8900, if(number % 20 = 0, 2, 1),                    -- mp: 95%x1 + 5%x2, avg 1.05
      number < 9180, multiIf(number % 100 < 75, 1, number % 100 < 95, 2, 3),  -- site: avg 1.30
      number < 9540, 3 + (cityHash64(number) % 8),                  -- B2B RU: 3-10, avg 6.5
      number < 9720, 3 + (cityHash64(number) % 8),
      number < 9850, 3 + (cityHash64(number) % 8),
      number < 9925, 4 + (cityHash64(number) % 9),                  -- B2B dxb: 4-12, avg 8
      3 + (cityHash64(number) % 6)                                  -- B2B ala: 3-8, avg 5.5
    ) AS line_count
  FROM numbers(10000)
)
ARRAY JOIN arrayMap(
  i -> if(
    number < 9180,
    multiIf(
      cityHash64(number * 31 + i) % 100 < 55, cityHash64(number * 37 + i) % 24,
      cityHash64(number * 31 + i) % 100 < 90, 24 + (cityHash64(number * 37 + i) % 56),
      80 + (cityHash64(number * 37 + i) % 80)
    ),
    cityHash64(number * 31 + i) % 160
  ),
  range(line_count)
) AS p;

-- sat_marking_code_gs1__1c__global: status for both the 160 SKU-level
-- templates ('issued') and the ~12,000 per-unit sample (25/60/15 split,
-- §11). gs1_gtin identities are synthetic (deterministic stem per SKU slot,
-- distinct from the reference package's ref__global GTINs), but each carries
-- the genuine GS1 mod-10 check digit so is_valid_gtin13 passes (§12 #7): the
-- 13th char comes from the pinned 160-digit string below, precomputed over
-- the 160 stems and asserted against reference/gs1.py's gtin13_check_digit
-- by tests/unit/test_generator_spec_invariants.py. serial_number carries the
-- per-unit distinction.
INSERT INTO rv.sat_marking_code_gs1__1c__global
    (marking_code_hk, load_ts, hash_diff, record_source,
     gs1_gtin, serial_number, marking_status, is_deleted)
SELECT
    MD5(marking_code_bk), now64(3), MD5(concat(marking_code_bk, '|gs1|v1')), '1c__global',
    gs1_gtin, serial_number, marking_status, 0
FROM (
  SELECT
    concat('CZ-SKU-', lpad(toString(number), 5, '0')) AS marking_code_bk,
    concat(
      toString(460 + (number % 10)),
      lpad(toString(200000 + number * 617), 9, '0'),
      substring('6520850863093096493187417410759759859852083086326086386419718742019752952985385309376309618641041041642975975208205308307631631974541874974298298598207537530960', number + 1, 1)
    ) AS gs1_gtin,
    CAST(NULL, 'Nullable(String)') AS serial_number,
    'issued' AS marking_status
  FROM numbers(160)
  UNION ALL
  SELECT
    concat('CZU-', lpad(toString(number % 160), 5, '0'), '-', lpad(toString(intDiv(number, 160)), 7, '0')) AS marking_code_bk,
    concat(
      toString(460 + ((number % 160) % 10)),
      lpad(toString(200000 + (number % 160) * 617), 9, '0'),
      substring('6520850863093096493187417410759759859852083086326086386419718742019752952985385309376309618641041041642975975208205308307631631974541874974298298598207537530960', (number % 160) + 1, 1)
    ) AS gs1_gtin,
    lpad(toString(intDiv(number, 160)), 7, '0') AS serial_number,
    multiIf(number % 100 < 25, 'issued', number % 100 < 85, 'in_circulation', 'withdrawn') AS marking_status
  FROM numbers(12000)
);

-- lnk_product_marking: links both the 160 SKU-level templates and the
-- ~12,000 per-unit codes to their product (no order dimension — this link
-- is product<->marking-code traceability, independent of any one sale).
INSERT INTO rv.lnk_product_marking (link_hk, product_hk, marking_code_hk, load_ts, record_source)
SELECT
    MD5(concat(product_bk, '|', marking_code_bk)),
    MD5(product_bk),
    MD5(marking_code_bk),
    now64(),
    '1c__global'
FROM (
  SELECT concat('SKU-', lpad(toString(number), 5, '0')) AS product_bk,
         concat('CZ-SKU-', lpad(toString(number), 5, '0')) AS marking_code_bk
  FROM numbers(160)
  UNION ALL
  SELECT concat('SKU-', lpad(toString(number % 160), 5, '0')) AS product_bk,
         concat('CZU-', lpad(toString(number % 160), 5, '0'), '-', lpad(toString(intDiv(number, 160)), 7, '0')) AS marking_code_bk
  FROM numbers(12000)
);

-- lnk_order_store: msk fulfils marketplace + D2C + its own B2B (central
-- warehouse, alternating msk-01/msk-02); regional branches fulfil their own
-- B2B only (domain.md §1 footprint).
INSERT INTO rv.lnk_order_store (link_hk, order_hk, store_hk, load_ts, record_source)
SELECT
    MD5(concat(order_bk, '|', store_code)),
    MD5(order_bk),
    MD5(store_code),
    now64(),
    '1c__global'
FROM (
  SELECT
    number,
    concat(
      multiIf(
        number < 8900, 'mp__msk',
        number < 9180, 'site__msk',
        number < 9540, 'bitrix__msk',
        number < 9720, 'bitrix__spb',
        number < 9850, 'bitrix__ekb',
        number < 9925, 'bitrix__dxb',
        'bitrix__ala'
      ),
      '__',
      lpad(toString(number), 7, '0')
    ) AS order_bk,
    multiIf(
      number < 9540, if(number % 2 = 0, 'msk-01', 'msk-02'),
      number < 9720, 'spb-01',
      number < 9850, 'ekb-01',
      number < 9925, 'dxb-01',
      'ala-01'
    ) AS store_code
  FROM numbers(10000)
);
