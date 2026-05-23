-- Satellite seed extension for the non-MSK branches.
-- Idempotent via hash_diff. Apply AFTER warehouse/agentflow/dv2/satellite_seed.sql
-- (which seeds the msk + dxb-personal slices); this file fills:
--   * sat_customer_personal__1c__{spb, ekb, ala}
--   * sat_customer_loyalty__bitrix__{spb, ekb}     -- dxb/ala intentionally skipped
--   * sat_customer_anon__1c__{spb, ekb, dxb, ala}
--   * sat_order_header__bitrix__{spb, ekb, dxb, ala}
--   * sat_order_pricing__1c__{spb, ekb, dxb, ala}

-- ============ CUSTOMER PII (spb) ============
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
    toDate('1960-01-01') + (number % (365 * 50)),
    true, 0
FROM numbers(2000)
WHERE number % 100 >= 40 AND number % 100 < 65;   -- spb slice (25%)

-- ============ CUSTOMER PII (ekb) ============
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
FROM numbers(2000)
WHERE number % 100 >= 65 AND number % 100 < 80;   -- ekb slice (15%)

-- ============ CUSTOMER PII (ala) ============
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
FROM numbers(2000)
WHERE number % 100 >= 90;   -- ala slice (10%)

-- ============ CUSTOMER LOYALTY (spb / ekb) ============
INSERT INTO rv.sat_customer_loyalty__bitrix__spb
    (customer_hk, load_ts, hash_diff, record_source,
     loyalty_segment, loyalty_points, last_visit_at, is_deleted)
SELECT
    MD5(toString(number)),
    now64(3),
    MD5(concat(toString(number), '|loy|v1')),
    'bitrix__spb',
    arrayElement(['vip','gold','silver','bronze','prospect'], (number % 5) + 1),
    toDecimal64((number * 13) % 50000, 2),
    now64(3) - toIntervalDay((number % 90)),
    0
FROM numbers(2000)
WHERE number % 100 >= 40 AND number % 100 < 65
  AND number % 5 != 0;   -- 80% coverage

INSERT INTO rv.sat_customer_loyalty__bitrix__ekb
    (customer_hk, load_ts, hash_diff, record_source,
     loyalty_segment, loyalty_points, last_visit_at, is_deleted)
SELECT
    MD5(toString(number)),
    now64(3),
    MD5(concat(toString(number), '|loy|v1')),
    'bitrix__ekb',
    arrayElement(['vip','gold','silver','bronze','prospect'], (number % 5) + 1),
    toDecimal64((number * 13) % 50000, 2),
    now64(3) - toIntervalDay((number % 90)),
    0
FROM numbers(2000)
WHERE number % 100 >= 65 AND number % 100 < 80
  AND number % 5 != 0;

-- ============ ANON SATS (spb / ekb / dxb / ala) ============
-- branch helper view inlined per insert; one anon row per customer per branch.
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
FROM numbers(2000)
WHERE number % 100 >= 40 AND number % 100 < 65;

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
FROM numbers(2000)
WHERE number % 100 >= 65 AND number % 100 < 80;

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
FROM numbers(2000)
WHERE number % 100 >= 80 AND number % 100 < 90;

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
FROM numbers(2000)
WHERE number % 100 >= 90;

-- ============ ORDER HEADER (spb / ekb / dxb / ala) ============
-- Single helper template; same order_hk derivation as synthetic_seed.sql.
INSERT INTO rv.sat_order_header__bitrix__spb
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat('bitrix__spb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat(toString(number), '|hdr|v1')),
    'bitrix__spb',
    now64(3) - toIntervalHour((number * 7) % (24 * 90)),
    arrayElement(['web','mobile','retail','call-center'], (number % 4) + 1),
    arrayElement(['new','paid','shipped','delivered','returned'], (number % 5) + 1),
    toDecimal64(500 + (number * 17) % 25000, 2),
    0
FROM numbers(10000)
WHERE number % 100 >= 40 AND number % 100 < 65;

INSERT INTO rv.sat_order_header__bitrix__ekb
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat('bitrix__ekb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat(toString(number), '|hdr|v1')),
    'bitrix__ekb',
    now64(3) - toIntervalHour((number * 7) % (24 * 90)),
    arrayElement(['web','mobile','retail','call-center'], (number % 4) + 1),
    arrayElement(['new','paid','shipped','delivered','returned'], (number % 5) + 1),
    toDecimal64(500 + (number * 17) % 25000, 2),
    0
FROM numbers(10000)
WHERE number % 100 >= 65 AND number % 100 < 80;

INSERT INTO rv.sat_order_header__bitrix__dxb
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat('bitrix__dxb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat(toString(number), '|hdr|v1')),
    'bitrix__dxb',
    now64(3) - toIntervalHour((number * 7) % (24 * 90)),
    arrayElement(['web','mobile','retail','call-center'], (number % 4) + 1),
    arrayElement(['new','paid','shipped','delivered','returned'], (number % 5) + 1),
    toDecimal64(500 + (number * 17) % 25000, 2),
    0
FROM numbers(10000)
WHERE number % 100 >= 80 AND number % 100 < 90;

INSERT INTO rv.sat_order_header__bitrix__ala
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat('bitrix__ala__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat(toString(number), '|hdr|v1')),
    'bitrix__ala',
    now64(3) - toIntervalHour((number * 7) % (24 * 90)),
    arrayElement(['web','mobile','retail','call-center'], (number % 4) + 1),
    arrayElement(['new','paid','shipped','delivered','returned'], (number % 5) + 1),
    toDecimal64(500 + (number * 17) % 25000, 2),
    0
FROM numbers(10000)
WHERE number % 100 >= 90;

-- ============ ORDER PRICING (spb / ekb / dxb / ala) ============
INSERT INTO rv.sat_order_pricing__1c__spb
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat('bitrix__spb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat(toString(number), '|prc|v1')),
    '1c__spb',
    toDecimal64(500 + (number * 17) % 25000, 2),
    toDecimal64((number * 3) % 1500, 2),
    toDecimal64((500 + (number * 17) % 25000) * 0.20, 2),
    toDecimal64(199 + (number % 5) * 100, 2),
    0
FROM numbers(10000)
WHERE number % 100 >= 40 AND number % 100 < 65;

INSERT INTO rv.sat_order_pricing__1c__ekb
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat('bitrix__ekb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat(toString(number), '|prc|v1')),
    '1c__ekb',
    toDecimal64(500 + (number * 17) % 25000, 2),
    toDecimal64((number * 3) % 1500, 2),
    toDecimal64((500 + (number * 17) % 25000) * 0.20, 2),
    toDecimal64(199 + (number % 5) * 100, 2),
    0
FROM numbers(10000)
WHERE number % 100 >= 65 AND number % 100 < 80;

INSERT INTO rv.sat_order_pricing__1c__dxb
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat('bitrix__dxb__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat(toString(number), '|prc|v1')),
    '1c__dxb',
    toDecimal64(500 + (number * 17) % 25000, 2),
    toDecimal64((number * 3) % 1500, 2),
    toDecimal64((500 + (number * 17) % 25000) * 0.05, 2),   -- DXB VAT 5%
    toDecimal64(199 + (number % 5) * 100, 2),
    0
FROM numbers(10000)
WHERE number % 100 >= 80 AND number % 100 < 90;

INSERT INTO rv.sat_order_pricing__1c__ala
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat('bitrix__ala__', lpad(toString(number), 7, '0'))),
    now64(3),
    MD5(concat(toString(number), '|prc|v1')),
    '1c__ala',
    toDecimal64(500 + (number * 17) % 25000, 2),
    toDecimal64((number * 3) % 1500, 2),
    toDecimal64((500 + (number * 17) % 25000) * 0.12, 2),   -- KZ VAT 12%
    toDecimal64(199 + (number % 5) * 100, 2),
    0
FROM numbers(10000)
WHERE number % 100 >= 90;
