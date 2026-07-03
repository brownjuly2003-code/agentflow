-- Minimal anon-sat seed for cold-offload demo.
-- Derives non-PII attributes (age_bucket / geo_region / segment) from a
-- deterministic hash of the customer number so the cold export has real
-- rows to ship without touching jurisdictional PII.
--
-- One row per msk customer: retail [0,2000) + dealer msk [2000,2190) —
-- 2,190 rows, matching hub_customer's msk band (synthetic_seed.sql header).
-- Re-runnable: hash_diff makes the satellite ReplacingMergeTree-friendly
-- even though it's MergeTree.

INSERT INTO rv.sat_customer_anon__1c__msk
    (customer_hk, load_ts, hash_diff, record_source,
     age_bucket, geo_region, customer_segment, is_deleted)
SELECT
    MD5(toString(number))                        AS customer_hk,
    now64(3)                                     AS load_ts,
    MD5(concat(toString(number), '|anon|v1'))    AS hash_diff,
    '1c__msk'                                    AS record_source,
    multiIf(
        number % 5 = 0, '18-24',
        number % 5 = 1, '25-34',
        number % 5 = 2, '35-44',
        number % 5 = 3, '45-54',
        '55+'
    )                                            AS age_bucket,
    multiIf(
        number % 7 < 3, 'msk-center',
        number % 7 < 5, 'msk-north',
        'msk-south'
    )                                            AS geo_region,
    multiIf(
        number % 4 = 0, 'vip',
        number % 4 = 1, 'regular',
        number % 4 = 2, 'churned',
        'new'
    )                                            AS customer_segment,
    0                                            AS is_deleted
FROM numbers(2190);   -- msk slice: retail [0,2000) + dealer msk [2000,2190)
