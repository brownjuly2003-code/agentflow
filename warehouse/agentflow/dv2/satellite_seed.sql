-- Satellite seed for the DV2.0 multi-branch demo.
-- Populates the satellites the synthetic_seed.sql skipped, so business_vault
-- views return non-NULL rows for PII / loyalty / order header / order pricing.
--
-- All faux PII is deterministically derived from the customer number so the
-- seed is repeatable and reproduces the same hash_diff on re-runs.

-- ============ CUSTOMER PII (1C, msk slice) ============
INSERT INTO rv.sat_customer_personal__1c__msk
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    MD5(toString(number))                                          AS customer_hk,
    now64(3)                                                       AS load_ts,
    MD5(concat(toString(number), '|pii|v1'))                       AS hash_diff,
    '1c__msk'                                                      AS record_source,
    arrayElement(['Anna','Boris','Dasha','Egor','Fedor','Galya','Ivan','Kira','Lena','Mark'],
                 (number % 10) + 1)                                AS first_name,
    arrayElement(['Ivanov','Petrov','Sidorov','Smirnov','Volkov','Orlov','Lebedev','Sokolov'],
                 (number % 8) + 1)                                 AS last_name,
    concat('cust', toString(number), '@example.test')              AS email,
    concat('+7916', lpad(toString(number % 10000000), 7, '0'))     AS phone,
    toDate('1960-01-01') + (number % (365 * 50))                   AS birth_date,
    true                                                           AS pii_flag,
    0                                                              AS is_deleted
FROM numbers(2000)
WHERE number % 100 < 40;   -- msk slice

-- ============ CUSTOMER PII (1C, dxb slice) ============
INSERT INTO rv.sat_customer_personal__1c__dxb
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    MD5(toString(number))                                          AS customer_hk,
    now64(3)                                                       AS load_ts,
    MD5(concat(toString(number), '|pii|v1'))                       AS hash_diff,
    '1c__dxb'                                                      AS record_source,
    arrayElement(['Aisha','Khalid','Layla','Omar','Sara','Yusuf','Mariam','Ahmed'],
                 (number % 8) + 1)                                 AS first_name,
    arrayElement(['Al-Sayed','Al-Maktoum','Hassan','Rashid','Hamdan','Saleh'],
                 (number % 6) + 1)                                 AS last_name,
    concat('cust', toString(number), '@example.ae')                AS email,
    concat('+9715', lpad(toString(number % 10000000), 7, '0'))     AS phone,
    toDate('1965-01-01') + (number % (365 * 45))                   AS birth_date,
    true                                                           AS pii_flag,
    0                                                              AS is_deleted
FROM numbers(2000)
WHERE number % 100 >= 80 AND number % 100 < 90;   -- dxb slice

-- ============ CUSTOMER LOYALTY (Bitrix, msk slice) ============
-- Bitrix is the loyalty source of truth. ~80% of msk customers have a row,
-- the rest are "no Bitrix profile yet" — they remain visible in
-- bv_customer_mdm__msk via the LEFT JOIN, with loyalty_source = NULL.
INSERT INTO rv.sat_customer_loyalty__bitrix__msk
    (customer_hk, load_ts, hash_diff, record_source,
     loyalty_segment, loyalty_points, last_visit_at, is_deleted)
SELECT
    MD5(toString(number))                                            AS customer_hk,
    now64(3)                                                         AS load_ts,
    MD5(concat(toString(number), '|loy|v1'))                         AS hash_diff,
    'bitrix__msk'                                                    AS record_source,
    arrayElement(['vip','gold','silver','bronze','prospect'],
                 (number % 5) + 1)                                   AS loyalty_segment,
    toDecimal64((number * 13) % 50000, 2)                            AS loyalty_points,
    now64(3) - toIntervalDay((number % 90))                          AS last_visit_at,
    0                                                                AS is_deleted
FROM numbers(2000)
WHERE number % 100 < 40           -- msk slice
  AND number % 5 != 0;            -- 80% coverage

-- ============ ORDER HEADER (Bitrix, msk slice) ============
INSERT INTO rv.sat_order_header__bitrix__msk
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(concat(
        'bitrix__',
        multiIf(number % 100 < 40, 'msk', number % 100 < 65, 'spb',
                number % 100 < 80, 'ekb', number % 100 < 90, 'dxb', 'ala'),
        '__',
        lpad(toString(number), 7, '0')
    ))                                                                AS order_hk,
    now64(3)                                                          AS load_ts,
    MD5(concat(toString(number), '|hdr|v1'))                          AS hash_diff,
    'bitrix__msk'                                                     AS record_source,
    now64(3) - toIntervalHour((number * 7) % (24 * 90))                AS order_date,
    arrayElement(['web','mobile','retail','call-center'],
                 (number % 4) + 1)                                    AS channel,
    arrayElement(['new','paid','shipped','delivered','returned'],
                 (number % 5) + 1)                                    AS order_status,
    toDecimal64(500 + (number * 17) % 25000, 2)                       AS total_amount,
    0                                                                 AS is_deleted
FROM numbers(10000)
WHERE number % 100 < 40;   -- msk slice = 4000 orders

-- ============ ORDER PRICING (1C, msk slice) ============
INSERT INTO rv.sat_order_pricing__1c__msk
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(concat(
        'bitrix__',
        multiIf(number % 100 < 40, 'msk', number % 100 < 65, 'spb',
                number % 100 < 80, 'ekb', number % 100 < 90, 'dxb', 'ala'),
        '__',
        lpad(toString(number), 7, '0')
    ))                                                                AS order_hk,
    now64(3)                                                          AS load_ts,
    MD5(concat(toString(number), '|prc|v1'))                          AS hash_diff,
    '1c__msk'                                                         AS record_source,
    toDecimal64(500 + (number * 17) % 25000, 2)                       AS subtotal_amount,
    toDecimal64((number * 3) % 1500, 2)                               AS discount_amount,
    toDecimal64((500 + (number * 17) % 25000) * 0.20, 2)              AS tax_amount,
    toDecimal64(199 + (number % 5) * 100, 2)                          AS shipping_cost,
    0                                                                 AS is_deleted
FROM numbers(10000)
WHERE number % 100 < 40;   -- msk slice = 4000 orders
