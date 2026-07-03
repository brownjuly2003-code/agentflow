-- Satellite seed extension for the non-MSK branches (own-brand
-- kitchen-appliance importer legend — numbering matches synthetic_seed.sql).
-- Idempotent via hash_diff. Apply AFTER warehouse/agentflow/dv2/satellite_seed.sql
-- (which seeds the msk + dxb-personal slices); this file fills:
--   * sat_customer_personal__1c__{spb, ekb, ala}   -- dealer bands only
--   * sat_customer_loyalty__bitrix__{spb, ekb}     -- dxb/ala intentionally skipped
--   * sat_customer_anon__1c__{spb, ekb, dxb, ala}
--   * sat_order_header__bitrix__{spb, ekb, dxb, ala}
--   * sat_order_pricing__1c__{spb, ekb, dxb, ala}
--
-- All remaining branches are B2B-only (domain.md §1: regional branches hold
-- dealer customers only; only msk fulfils retail/marketplace/D2C).

-- ============ CUSTOMER PII (dealer spb [2190,2290)) ============
INSERT INTO rv.sat_customer_personal__1c__spb
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    MD5(toString(number)),
    now64(3),
    MD5(concat(toString(number), '|pii|v1')),
    '1c__spb',
    arrayElement(['Anna','Boris','Dasha','Egor','Fedor','Galya','Ivan','Kira','Lena','Mark'], (number % 10) + 1),
    arrayElement(['Ivanov','Petrov','Sidorov','Smirnov','Volkov','Orlov','Lebedev','Sokolov'], (number % 8) + 1),
    concat('cust', toString(number), '@example.test'),
    concat('+7812', lpad(toString(number % 10000000), 7, '0')),
    toDate('1960-01-01') + (number % (365 * 50)),   -- dealer: birth_date always filled (§8)
    true, 0
FROM numbers(2290)
WHERE number >= 2190;   -- dealer spb [2190,2290)

-- ============ CUSTOMER PII (dealer ekb [2290,2360)) ============
INSERT INTO rv.sat_customer_personal__1c__ekb
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    MD5(toString(number)),
    now64(3),
    MD5(concat(toString(number), '|pii|v1')),
    '1c__ekb',
    arrayElement(['Anna','Boris','Dasha','Egor','Fedor','Galya','Ivan','Kira','Lena','Mark'], (number % 10) + 1),
    arrayElement(['Ivanov','Petrov','Sidorov','Smirnov','Volkov','Orlov','Lebedev','Sokolov'], (number % 8) + 1),
    concat('cust', toString(number), '@example.test'),
    concat('+7343', lpad(toString(number % 10000000), 7, '0')),
    toDate('1960-01-01') + (number % (365 * 50)),
    true, 0
FROM numbers(2360)
WHERE number >= 2290;   -- dealer ekb [2290,2360)

-- ============ CUSTOMER PII (dealer ala [2420,2500)) ============
INSERT INTO rv.sat_customer_personal__1c__ala
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    MD5(toString(number)),
    now64(3),
    MD5(concat(toString(number), '|pii|v1')),
    '1c__ala',
    arrayElement(['Aigerim','Daniyar','Madina','Nurlan','Saltanat','Timur','Zhanna','Bauyrzhan'], (number % 8) + 1),
    arrayElement(['Aitkulov','Bekturov','Yerlanov','Zhumagulov','Sagintayev','Nurpeisov'], (number % 6) + 1),
    concat('cust', toString(number), '@example.kz'),
    concat('+7727', lpad(toString(number % 10000000), 7, '0')),
    toDate('1965-01-01') + (number % (365 * 45)),
    true, 0
FROM numbers(2500)
WHERE number >= 2420;   -- dealer ala [2420,2500)

-- ============ CUSTOMER LOYALTY (dealer spb / ekb, 80% coverage) ============
-- dxb/ala dealers intentionally skipped: contract terms, not the bonus
-- program (domain.md §5.2, generator-spec.md §8/§12 #12).
INSERT INTO rv.sat_customer_loyalty__bitrix__spb
    (customer_hk, load_ts, hash_diff, record_source,
     loyalty_segment, loyalty_points, last_visit_at, is_deleted)
SELECT
    MD5(toString(number)),
    now64(3),
    MD5(concat(toString(number), '|loy|v1')),
    'bitrix__spb',
    multiIf(number % 5 < 2, 'core', number % 5 < 4, 'mid', 'tail'),
    toDecimal64((number * 13) % 9000, 2),
    now64(3) - toIntervalDay((number % 90)),
    0
FROM numbers(2290)
WHERE number >= 2190
  AND number % 5 != 0;   -- 80% coverage

INSERT INTO rv.sat_customer_loyalty__bitrix__ekb
    (customer_hk, load_ts, hash_diff, record_source,
     loyalty_segment, loyalty_points, last_visit_at, is_deleted)
SELECT
    MD5(toString(number)),
    now64(3),
    MD5(concat(toString(number), '|loy|v1')),
    'bitrix__ekb',
    multiIf(number % 5 < 2, 'core', number % 5 < 4, 'mid', 'tail'),
    toDecimal64((number * 13) % 9000, 2),
    now64(3) - toIntervalDay((number % 90)),
    0
FROM numbers(2360)
WHERE number >= 2290
  AND number % 5 != 0;

-- ============ ANON SATS (spb / ekb / dxb / ala dealer bands) ============
-- One anon row per dealer customer per branch. msk anon lives in
-- cold_offload_seed.sql (covers retail + dealer msk together).
INSERT INTO rv.sat_customer_anon__1c__spb
    (customer_hk, load_ts, hash_diff, record_source,
     age_bucket, geo_region, customer_segment, is_deleted)
SELECT
    MD5(toString(number)), now64(3),
    MD5(concat(toString(number), '|anon|v1')), '1c__spb',
    arrayElement(['18-24','25-34','35-44','45-54','55+'], (number % 5) + 1),
    arrayElement(['spb-center','spb-north','spb-south'], (number % 3) + 1),
    arrayElement(['vip','regular','churned','new'], (number % 4) + 1),
    0
FROM numbers(2290)
WHERE number >= 2190;

INSERT INTO rv.sat_customer_anon__1c__ekb
    (customer_hk, load_ts, hash_diff, record_source,
     age_bucket, geo_region, customer_segment, is_deleted)
SELECT
    MD5(toString(number)), now64(3),
    MD5(concat(toString(number), '|anon|v1')), '1c__ekb',
    arrayElement(['18-24','25-34','35-44','45-54','55+'], (number % 5) + 1),
    arrayElement(['ekb-center','ekb-vtuz'], (number % 2) + 1),
    arrayElement(['vip','regular','churned','new'], (number % 4) + 1),
    0
FROM numbers(2360)
WHERE number >= 2290;

INSERT INTO rv.sat_customer_anon__1c__dxb
    (customer_hk, load_ts, hash_diff, record_source,
     age_bucket, geo_region, customer_segment, is_deleted)
SELECT
    MD5(toString(number)), now64(3),
    MD5(concat(toString(number), '|anon|v1')), '1c__dxb',
    arrayElement(['18-24','25-34','35-44','45-54','55+'], (number % 5) + 1),
    arrayElement(['dxb-marina','dxb-downtown','dxb-deira'], (number % 3) + 1),
    arrayElement(['vip','regular','churned','new'], (number % 4) + 1),
    0
FROM numbers(2420)
WHERE number >= 2360;

INSERT INTO rv.sat_customer_anon__1c__ala
    (customer_hk, load_ts, hash_diff, record_source,
     age_bucket, geo_region, customer_segment, is_deleted)
SELECT
    MD5(toString(number)), now64(3),
    MD5(concat(toString(number), '|anon|v1')), '1c__ala',
    arrayElement(['18-24','25-34','35-44','45-54','55+'], (number % 5) + 1),
    arrayElement(['ala-medeu','ala-bostandyk','ala-almaly'], (number % 3) + 1),
    arrayElement(['vip','regular','churned','new'], (number % 4) + 1),
    0
FROM numbers(2500)
WHERE number >= 2420;

-- ============ ORDER HEADER (B2B: spb / ekb / dxb / ala) ============
-- channel = 'b2b' everywhere here (these branches carry no marketplace/D2C
-- volume). Same status-flow weights as msk (domain.md §5.1).
INSERT INTO rv.sat_order_header__bitrix__spb
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat('bitrix__spb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat('bitrix__spb__', lpad(toString(number), 7, '0'), '|hdr|v1')),
    'bitrix__spb',
    now64(3) - toIntervalHour((number * 7) % (24 * 21)),
    'b2b',
    multiIf(number % 100 < 8, 'pending', number % 100 < 18, 'confirmed',
            number % 100 < 30, 'shipped', number % 100 < 92, 'delivered', 'cancelled'),
    toDecimal64(30000 + (number * 137) % 50001, 2),
    0
FROM numbers(9720)
WHERE number >= 9540;   -- B2B spb [9540,9720)

INSERT INTO rv.sat_order_header__bitrix__ekb
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat('bitrix__ekb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat('bitrix__ekb__', lpad(toString(number), 7, '0'), '|hdr|v1')),
    'bitrix__ekb',
    now64(3) - toIntervalHour((number * 7) % (24 * 21)),
    'b2b',
    multiIf(number % 100 < 8, 'pending', number % 100 < 18, 'confirmed',
            number % 100 < 30, 'shipped', number % 100 < 92, 'delivered', 'cancelled'),
    toDecimal64(30000 + (number * 137) % 50001, 2),
    0
FROM numbers(9850)
WHERE number >= 9720;   -- B2B ekb [9720,9850)

INSERT INTO rv.sat_order_header__bitrix__dxb
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat('bitrix__dxb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat('bitrix__dxb__', lpad(toString(number), 7, '0'), '|hdr|v1')),
    'bitrix__dxb',
    now64(3) - toIntervalHour((number * 7) % (24 * 21)),
    'b2b',
    multiIf(number % 100 < 8, 'pending', number % 100 < 18, 'confirmed',
            number % 100 < 30, 'shipped', number % 100 < 92, 'delivered', 'cancelled'),
    toDecimal64(60000 + (number * 191) % 70001, 2),   -- export pallets: thinner margin, bigger tickets (§5)
    0
FROM numbers(9925)
WHERE number >= 9850;   -- B2B dxb [9850,9925)

INSERT INTO rv.sat_order_header__bitrix__ala
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat('bitrix__ala__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat('bitrix__ala__', lpad(toString(number), 7, '0'), '|hdr|v1')),
    'bitrix__ala',
    now64(3) - toIntervalHour((number * 7) % (24 * 21)),
    'b2b',
    multiIf(number % 100 < 8, 'pending', number % 100 < 18, 'confirmed',
            number % 100 < 30, 'shipped', number % 100 < 92, 'delivered', 'cancelled'),
    toDecimal64(25000 + (number * 151) % 45001, 2),
    0
FROM numbers(10000)
WHERE number >= 9925;   -- B2B ala [9925,10000)

-- ============ ORDER PRICING (B2B: spb / ekb / dxb / ala) ============
-- RU VAT 20% (spb/ekb); UAE VAT 5% (dxb); KZ VAT 12% (ala).
INSERT INTO rv.sat_order_pricing__1c__spb
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat('bitrix__spb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat('bitrix__spb__', lpad(toString(number), 7, '0'), '|prc|v1')),
    '1c__spb',
    toDecimal64(30000 + (number * 137) % 50001, 2),
    toDecimal64((30000 + (number * 137) % 50001) * 0.02 * (number % 4), 2),
    toDecimal64((30000 + (number * 137) % 50001) * 0.20, 2),
    toDecimal64(500 + (number % 3) * 300, 2),
    0
FROM numbers(9720)
WHERE number >= 9540;

INSERT INTO rv.sat_order_pricing__1c__ekb
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat('bitrix__ekb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat('bitrix__ekb__', lpad(toString(number), 7, '0'), '|prc|v1')),
    '1c__ekb',
    toDecimal64(30000 + (number * 137) % 50001, 2),
    toDecimal64((30000 + (number * 137) % 50001) * 0.02 * (number % 4), 2),
    toDecimal64((30000 + (number * 137) % 50001) * 0.20, 2),
    toDecimal64(500 + (number % 3) * 300, 2),
    0
FROM numbers(9850)
WHERE number >= 9720;

INSERT INTO rv.sat_order_pricing__1c__dxb
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat('bitrix__dxb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat('bitrix__dxb__', lpad(toString(number), 7, '0'), '|prc|v1')),
    '1c__dxb',
    toDecimal64(60000 + (number * 191) % 70001, 2),
    toDecimal64((60000 + (number * 191) % 70001) * 0.02 * (number % 4), 2),
    toDecimal64((60000 + (number * 191) % 70001) * 0.05, 2),   -- DXB VAT 5%
    toDecimal64(500 + (number % 3) * 300, 2),
    0
FROM numbers(9925)
WHERE number >= 9850;

INSERT INTO rv.sat_order_pricing__1c__ala
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat('bitrix__ala__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat('bitrix__ala__', lpad(toString(number), 7, '0'), '|prc|v1')),
    '1c__ala',
    toDecimal64(25000 + (number * 151) % 45001, 2),
    toDecimal64((25000 + (number * 151) % 45001) * 0.02 * (number % 4), 2),
    toDecimal64((25000 + (number * 151) % 45001) * 0.12, 2),   -- KZ VAT 12%
    toDecimal64(500 + (number % 3) * 300, 2),
    0
FROM numbers(10000)
WHERE number >= 9925;
