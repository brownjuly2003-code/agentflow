-- Satellite seed for the DV2.0 multi-branch demo (own-brand kitchen-appliance
-- importer legend — see synthetic_seed.sql header for the customer/order
-- numbering this file re-slices against).
-- Populates the satellites the synthetic_seed.sql skipped, so business_vault
-- views return non-NULL rows for PII / loyalty / order header / order pricing.
-- This file: msk (retail + dealer) PII/loyalty/orders, dxb dealer PII.
-- satellite_seed_all_branches.sql: spb/ekb/ala PII+loyalty, all branches'
-- anon sats and remaining order header/pricing.
--
-- All faux PII is deterministically derived from the customer/order number
-- so the seed is repeatable and reproduces the same hash_diff on re-runs.

-- ============ CUSTOMER PII (1C, msk: retail [0,2000) + dealer [2000,2190)) ==
-- generator-spec.md §8: dealer birth_date is dense (campaigns query it);
-- retail stays sparse (~40% filled). Phone prefix +7495 (msk landline code).
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
    concat('+7495', lpad(toString(number % 10000000), 7, '0'))     AS phone,
    if(number >= 2000 OR number % 5 < 2,                            -- dealer: 100%; retail: 40%
       toDate('1960-01-01') + (number % (365 * 50)), NULL)         AS birth_date,
    true                                                           AS pii_flag,
    0                                                              AS is_deleted
FROM numbers(2190);   -- retail [0,2000) + dealer msk [2000,2190)

-- ============ CUSTOMER PII (1C, dealer dxb [2360,2420)) ============
-- AE-appropriate names/phones (+971, latin transliteration) — dealer
-- contacts there are Gulf trading companies' buyers (§8). Dense birth_date.
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
FROM numbers(2420)
WHERE number >= 2360;   -- dealer dxb [2360,2420)

-- ============ CUSTOMER LOYALTY (Bitrix, dealer msk [2000,2190)) ============
-- Bitrix is the retro-bonus source of truth. Dealer-only (loyalty is
-- meaningless for retail here — domain.md §5.2/§8). ~80% coverage: the rest
-- are "no Bitrix profile yet", visible via the LEFT JOIN with loyalty_source
-- = NULL. loyalty_segment now reads core/mid/tail (the ordering-frequency
-- tiers, generator-spec.md §7/§8), not the old vip/gold/silver vocabulary.
-- loyalty_points capped at legend.LOYALTY_POINTS_MAX_RUB (9,000 ₽) — proven
-- in test_generator_spec_invariants.py to be <= 3% of the smallest plausible
-- trailing-quarter dealer spend (§12 invariant #12).
INSERT INTO rv.sat_customer_loyalty__bitrix__msk
    (customer_hk, load_ts, hash_diff, record_source,
     loyalty_segment, loyalty_points, last_visit_at, is_deleted)
SELECT
    MD5(toString(number))                                            AS customer_hk,
    now64(3)                                                         AS load_ts,
    MD5(concat(toString(number), '|loy|v1'))                         AS hash_diff,
    'bitrix__msk'                                                    AS record_source,
    multiIf(number % 5 < 2, 'core', number % 5 < 4, 'mid', 'tail')   AS loyalty_segment,
    toDecimal64((number * 13) % 9000, 2)                             AS loyalty_points,
    now64(3) - toIntervalDay((number % 90))                          AS last_visit_at,
    0                                                                AS is_deleted
FROM numbers(2190)
WHERE number >= 2000            -- dealer msk slice only
  AND number % 5 != 0;          -- 80% coverage

-- ============ ORDER HEADER (Bitrix, msk: mp+site+B2B [0,9540)) ============
-- channel: marketplace / d2c / b2b (generator-spec.md §2). Status flow
-- pending -> confirmed -> shipped -> delivered / cancelled, steady-state
-- weights 8/10/12/62/8 (domain.md §5.1).
INSERT INTO rv.sat_order_header__bitrix__msk
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(order_bk)                                                      AS order_hk,
    now64(3)                                                           AS load_ts,
    MD5(concat(order_bk, '|hdr|v1'))                                   AS hash_diff,
    'bitrix__msk'                                                      AS record_source,
    now64(3) - toIntervalHour((number * 7) % (24 * 21))                AS order_date,
    channel,
    multiIf(
      number % 100 < 8, 'pending',
      number % 100 < 18, 'confirmed',
      number % 100 < 30, 'shipped',
      number % 100 < 92, 'delivered',
      'cancelled'
    )                                                                  AS order_status,
    total_amount,
    0                                                                  AS is_deleted
FROM (
  SELECT
    number,
    concat(
      multiIf(number < 8900, 'mp__msk', number < 9180, 'site__msk', 'bitrix__msk'),
      '__', lpad(toString(number), 7, '0')
    ) AS order_bk,
    multiIf(number < 8900, 'marketplace', number < 9180, 'd2c', 'b2b') AS channel,
    multiIf(
      number < 8900, toDecimal64(1500 + (number * 17) % 1501, 2),      -- marketplace: 1.5k-3.0k
      number < 9180, toDecimal64(2000 + (number * 23) % 3001, 2),      -- D2C: 2.0k-5.0k
      toDecimal64(30000 + (number * 137) % 50001, 2)                   -- B2B msk: 30k-80k
    ) AS total_amount
  FROM numbers(9540)
);

-- ============ ORDER PRICING (1C, msk: mp+site+B2B [0,9540)) ============
-- subtotal mirrors header.total_amount (pre-tax); RU VAT 20%.
INSERT INTO rv.sat_order_pricing__1c__msk
    (order_hk, load_ts, hash_diff, record_source,
     subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted)
SELECT
    MD5(order_bk)                                                      AS order_hk,
    now64(3)                                                           AS load_ts,
    MD5(concat(order_bk, '|prc|v1'))                                   AS hash_diff,
    '1c__msk'                                                          AS record_source,
    subtotal_amount,
    toDecimal64(subtotal_amount * 0.02 * (number % 4), 2)              AS discount_amount,
    toDecimal64(subtotal_amount * 0.20, 2)                             AS tax_amount,
    toDecimal64(if(number < 9180, 199 + (number % 5) * 100, 500 + (number % 3) * 300), 2) AS shipping_cost,
    0                                                                  AS is_deleted
FROM (
  SELECT
    number,
    concat(
      multiIf(number < 8900, 'mp__msk', number < 9180, 'site__msk', 'bitrix__msk'),
      '__', lpad(toString(number), 7, '0')
    ) AS order_bk,
    multiIf(
      number < 8900, toDecimal64(1500 + (number * 17) % 1501, 2),
      number < 9180, toDecimal64(2000 + (number * 23) % 3001, 2),
      toDecimal64(30000 + (number * 137) % 50001, 2)
    ) AS subtotal_amount
  FROM numbers(9540)
);
