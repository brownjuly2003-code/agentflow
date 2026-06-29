/*
Purpose: Canonical customer record for the SPB branch.
Layer:   Business Vault.
Branch:  spb (RU jurisdiction; same conflict policy as MSK).
Hub admission: splitByString('__', record_source)[2] = 'spb' (source-agnostic:
         1c__/pg_ops__/x5__ all integrated, not only 1C; audit_28_06_26 #12;
         mirrors the PostgreSQL port's split_part(record_source,'__',2)).
*/
CREATE OR REPLACE VIEW rv.bv_customer_mdm__spb AS
WITH
    personal AS (
        SELECT
            customer_hk,
            argMax(first_name, load_ts) AS first_name,
            argMax(last_name, load_ts)  AS last_name,
            argMax(email, load_ts)      AS email,
            argMax(phone, load_ts)      AS phone,
            argMax(birth_date, load_ts) AS birth_date,
            max(load_ts)                AS pii_seen_at
        FROM rv.sat_customer_personal__1c__spb
        WHERE is_deleted = 0
        GROUP BY customer_hk
    ),
    loyalty AS (
        SELECT
            customer_hk,
            argMax(loyalty_segment, load_ts) AS loyalty_segment,
            argMax(loyalty_points, load_ts)  AS loyalty_points,
            argMax(last_visit_at, load_ts)   AS last_visit_at,
            max(load_ts)                     AS loyalty_seen_at
        FROM rv.sat_customer_loyalty__bitrix__spb
        WHERE is_deleted = 0
        GROUP BY customer_hk
    ),
    spb_hub AS (
        SELECT customer_hk, customer_bk
        FROM rv.hub_customer
        WHERE splitByString('__', record_source)[2] = 'spb'
    )
SELECT
    h.customer_hk                                  AS customer_hk,
    h.customer_bk                                  AS customer_bk,
    'spb'                                          AS branch,
    p.first_name                                   AS first_name,
    p.last_name                                    AS last_name,
    p.email                                        AS email,
    p.phone                                        AS phone,
    p.birth_date                                   AS birth_date,
    l.loyalty_segment                              AS loyalty_segment,
    l.loyalty_points                               AS loyalty_points,
    l.last_visit_at                                AS last_visit_at,
    if(p.customer_hk != toFixedString('', 16), '1c__spb', NULL)     AS pii_source,
    if(l.customer_hk != toFixedString('', 16), 'bitrix__spb', NULL) AS loyalty_source,
    greatest(coalesce(p.pii_seen_at, toDateTime64(0, 3)),
             coalesce(l.loyalty_seen_at, toDateTime64(0, 3)))       AS last_seen_at
FROM spb_hub h
LEFT JOIN personal p ON h.customer_hk = p.customer_hk
LEFT JOIN loyalty  l ON h.customer_hk = l.customer_hk;
