/*
Purpose: Canonical customer record for the DXB branch.
Layer:   Business Vault.
Branch:  dxb (UAE jurisdiction — PII never crosses into the MSK view).
Conflict policy:
  - PII — 1C is the only PII source available in DXB at this point.
  - Loyalty — not yet wired in for DXB (Bitrix24 sat is MSK-only); the view
    keeps the loyalty columns for schema parity with bv_customer_mdm__msk so
    downstream marts can UNION ALL the two branches without renaming.
*/
CREATE OR REPLACE VIEW rv.bv_customer_mdm__dxb AS
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
        FROM rv.sat_customer_personal__1c__dxb
        WHERE is_deleted = 0
        GROUP BY customer_hk
    ),
    dxb_hub AS (
        SELECT customer_hk, customer_bk
        FROM rv.hub_customer
        WHERE record_source = '1c__dxb'
    )
SELECT
    h.customer_hk                AS customer_hk,
    h.customer_bk                AS customer_bk,
    'dxb'                        AS branch,
    p.first_name                 AS first_name,
    p.last_name                  AS last_name,
    p.email                      AS email,
    p.phone                      AS phone,
    p.birth_date                 AS birth_date,
    CAST(NULL AS Nullable(String))       AS loyalty_segment,
    CAST(NULL AS Nullable(Decimal(18, 2))) AS loyalty_points,
    CAST(NULL AS Nullable(DateTime64(3)))  AS last_visit_at,
    if(p.customer_hk != toFixedString('', 16), '1c__dxb', NULL) AS pii_source,
    CAST(NULL AS Nullable(String))       AS loyalty_source,
    coalesce(p.pii_seen_at, toDateTime64(0, 3)) AS last_seen_at
FROM dxb_hub h
LEFT JOIN personal p ON h.customer_hk = p.customer_hk;
