/*
Purpose: Canonical order row joining Bitrix order header, 1C pricing, and
         (where present) Wildberries marketplace state, attributed to a
         customer + branch.
Layer:   Business Vault (read-only view over raw_vault).
Dialect: postgresql.
Branch:  all 5 (header + pricing satellites are UNION ALL'd across
         msk / spb / ekb / dxb / ala). Orders carry their own branch column
         derived from hub_order.record_source.
Conflict policy:
  - Order header (status / channel / order_date / total) — Bitrix wins.
  - Order pricing (subtotal / discount / tax / shipping) — 1C wins
    (effective tax rates differ per jurisdiction: 20% RU, 5% UAE, 12% KZ).
  - Marketplace (wb_status / wb_commission / return_window) — only available
    for the MSK Wildberries integration today.
SCD2 collapse: latest row per order_hk via DISTINCT ON (order_hk) ORDER BY
         order_hk, load_ts DESC — the PostgreSQL equivalent of ClickHouse
         argMax(.., load_ts). The reconstruction is join-heavy by design,
         which is why the vault runs on PostgreSQL rather than ClickHouse.
*/
CREATE OR REPLACE VIEW rv.bv_order_canonical AS
WITH
    header_raw AS (
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__bitrix__msk WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__bitrix__spb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__bitrix__ekb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__bitrix__dxb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__bitrix__ala WHERE is_deleted = 0
        -- 1C / X5 Retail Hero order headers (per-branch), so real X5 volume
        -- flows through to bv_order_canonical and the branch_pnl mart.
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__1c__msk WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__1c__spb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__1c__ekb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__1c__dxb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
        FROM rv.sat_order_header__1c__ala WHERE is_deleted = 0
    ),
    header AS (
        SELECT DISTINCT ON (order_hk)
            order_hk, order_date, channel, order_status, total_amount
        FROM header_raw
        ORDER BY order_hk, load_ts DESC
    ),
    pricing_raw AS (
        SELECT order_hk, subtotal_amount, discount_amount, tax_amount, shipping_cost, load_ts
        FROM rv.sat_order_pricing__1c__msk WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, subtotal_amount, discount_amount, tax_amount, shipping_cost, load_ts
        FROM rv.sat_order_pricing__1c__spb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, subtotal_amount, discount_amount, tax_amount, shipping_cost, load_ts
        FROM rv.sat_order_pricing__1c__ekb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, subtotal_amount, discount_amount, tax_amount, shipping_cost, load_ts
        FROM rv.sat_order_pricing__1c__dxb WHERE is_deleted = 0
        UNION ALL
        SELECT order_hk, subtotal_amount, discount_amount, tax_amount, shipping_cost, load_ts
        FROM rv.sat_order_pricing__1c__ala WHERE is_deleted = 0
    ),
    pricing AS (
        SELECT DISTINCT ON (order_hk)
            order_hk, subtotal_amount, discount_amount, tax_amount, shipping_cost
        FROM pricing_raw
        ORDER BY order_hk, load_ts DESC
    ),
    marketplace AS (
        SELECT DISTINCT ON (order_hk)
            order_hk,
            wb_status,
            wb_commission,
            return_window_until AS wb_return_window_until
        FROM rv.sat_order_marketplace__wb__msk
        WHERE is_deleted = 0
        ORDER BY order_hk, load_ts DESC
    ),
    order_branch AS (
        SELECT
            order_hk,
            order_bk,
            split_part(record_source, '__', 2) AS branch
        FROM rv.hub_order
    ),
    order_customer AS (
        SELECT DISTINCT ON (order_hk) order_hk, customer_hk
        FROM rv.lnk_order_customer
        ORDER BY order_hk, load_ts DESC
    ),
    order_store AS (
        SELECT DISTINCT ON (order_hk) order_hk, store_hk
        FROM rv.lnk_order_store
        ORDER BY order_hk, load_ts DESC
    )
SELECT
    o.order_hk           AS order_hk,
    o.order_bk           AS order_bk,
    o.branch             AS branch,
    oc.customer_hk       AS customer_hk,
    os.store_hk          AS store_hk,
    h.order_date         AS order_date,
    h.channel            AS channel,
    h.order_status       AS order_status,
    h.total_amount       AS total_amount,
    p.subtotal_amount    AS subtotal_amount,
    p.discount_amount    AS discount_amount,
    p.tax_amount         AS tax_amount,
    p.shipping_cost      AS shipping_cost,
    m.wb_status          AS wb_status,
    m.wb_commission      AS wb_commission,
    m.wb_return_window_until AS wb_return_window_until,
    CASE WHEN h.order_hk IS NOT NULL THEN 'bitrix__' || o.branch END AS header_source,
    CASE WHEN p.order_hk IS NOT NULL THEN '1c__' || o.branch END     AS pricing_source,
    CASE WHEN m.order_hk IS NOT NULL THEN 'wb__msk' END              AS marketplace_source
FROM order_branch o
LEFT JOIN header      h ON o.order_hk = h.order_hk
LEFT JOIN pricing     p ON o.order_hk = p.order_hk
LEFT JOIN marketplace m ON o.order_hk = m.order_hk
LEFT JOIN order_customer oc ON o.order_hk = oc.order_hk
LEFT JOIN order_store    os ON o.order_hk = os.order_hk;


/*
Purpose: Canonical customer record per branch (PostgreSQL port of the
         ClickHouse business_vault/bv_customer_mdm__<branch>.sql views).
Layer:   Business Vault (read-only view over raw_vault).
Dialect: postgresql.
Branch:  one view per jurisdiction by design — PII stays in branch.
Hub admission: split_part(record_source,'__',2) = '<branch>', so a customer
         promoted under ANY source convention (1c__<branch>, pg_ops__<branch>,
         mp__<branch>, ...) is integrated. This mirrors bv_order_canonical's
         order_branch derivation above. The ClickHouse views hard-code
         record_source = '1c__<branch>', which silently dropped every OLTP- and
         marketplace-promoted customer (record_source pg_ops__/mp__) from the MDM result
         (audit_28_06_26 #12). The hash keys were never incompatible —
         customer_hk = md5(business_key) is identical across loaders; only the
         hub record_source filter excluded them. split_part is the source-
         agnostic fix and needs no data migration (view DDL only).
SCD2 collapse: DISTINCT ON (customer_hk) ORDER BY load_ts DESC is the
         PostgreSQL equivalent of ClickHouse argMax(.., load_ts). A LEFT JOIN
         miss yields NULL in PostgreSQL (vs ClickHouse's zero-filled
         FixedString), so source flags test `IS NOT NULL` rather than
         `!= toFixedString('', 16)`.
Conflict policy:
  - PII (name/email/phone) — 1C wins (source of truth for invoicing).
  - Loyalty (segment/points/last_visit) — Bitrix wins (live CRM state).
  - DXB/ALA: Bitrix loyalty is not wired in (UAE/KZ); loyalty columns are kept
    NULL for schema parity so marts can UNION ALL all branches.
*/
CREATE OR REPLACE VIEW rv.bv_customer_mdm__msk AS
WITH
    personal AS (
        SELECT DISTINCT ON (customer_hk)
            customer_hk, first_name, last_name, email, phone, birth_date,
            load_ts AS pii_seen_at
        FROM rv.sat_customer_personal__1c__msk WHERE is_deleted = 0
        ORDER BY customer_hk, load_ts DESC
    ),
    loyalty AS (
        SELECT DISTINCT ON (customer_hk)
            customer_hk, loyalty_segment, loyalty_points, last_visit_at,
            load_ts AS loyalty_seen_at
        FROM rv.sat_customer_loyalty__bitrix__msk WHERE is_deleted = 0
        ORDER BY customer_hk, load_ts DESC
    ),
    branch_hub AS (
        SELECT customer_hk, customer_bk FROM rv.hub_customer
        WHERE split_part(record_source, '__', 2) = 'msk'
    )
SELECT
    h.customer_hk     AS customer_hk,
    h.customer_bk     AS customer_bk,
    'msk'             AS branch,
    p.first_name      AS first_name,
    p.last_name       AS last_name,
    p.email           AS email,
    p.phone           AS phone,
    p.birth_date      AS birth_date,
    l.loyalty_segment AS loyalty_segment,
    l.loyalty_points  AS loyalty_points,
    l.last_visit_at   AS last_visit_at,
    CASE WHEN p.customer_hk IS NOT NULL THEN '1c__msk' END     AS pii_source,
    CASE WHEN l.customer_hk IS NOT NULL THEN 'bitrix__msk' END AS loyalty_source,
    GREATEST(coalesce(p.pii_seen_at, '1970-01-01'::timestamp(3)),
             coalesce(l.loyalty_seen_at, '1970-01-01'::timestamp(3))) AS last_seen_at
FROM branch_hub h
LEFT JOIN personal p ON h.customer_hk = p.customer_hk
LEFT JOIN loyalty  l ON h.customer_hk = l.customer_hk;

CREATE OR REPLACE VIEW rv.bv_customer_mdm__spb AS
WITH
    personal AS (
        SELECT DISTINCT ON (customer_hk)
            customer_hk, first_name, last_name, email, phone, birth_date,
            load_ts AS pii_seen_at
        FROM rv.sat_customer_personal__1c__spb WHERE is_deleted = 0
        ORDER BY customer_hk, load_ts DESC
    ),
    loyalty AS (
        SELECT DISTINCT ON (customer_hk)
            customer_hk, loyalty_segment, loyalty_points, last_visit_at,
            load_ts AS loyalty_seen_at
        FROM rv.sat_customer_loyalty__bitrix__spb WHERE is_deleted = 0
        ORDER BY customer_hk, load_ts DESC
    ),
    branch_hub AS (
        SELECT customer_hk, customer_bk FROM rv.hub_customer
        WHERE split_part(record_source, '__', 2) = 'spb'
    )
SELECT
    h.customer_hk     AS customer_hk,
    h.customer_bk     AS customer_bk,
    'spb'             AS branch,
    p.first_name      AS first_name,
    p.last_name       AS last_name,
    p.email           AS email,
    p.phone           AS phone,
    p.birth_date      AS birth_date,
    l.loyalty_segment AS loyalty_segment,
    l.loyalty_points  AS loyalty_points,
    l.last_visit_at   AS last_visit_at,
    CASE WHEN p.customer_hk IS NOT NULL THEN '1c__spb' END     AS pii_source,
    CASE WHEN l.customer_hk IS NOT NULL THEN 'bitrix__spb' END AS loyalty_source,
    GREATEST(coalesce(p.pii_seen_at, '1970-01-01'::timestamp(3)),
             coalesce(l.loyalty_seen_at, '1970-01-01'::timestamp(3))) AS last_seen_at
FROM branch_hub h
LEFT JOIN personal p ON h.customer_hk = p.customer_hk
LEFT JOIN loyalty  l ON h.customer_hk = l.customer_hk;

CREATE OR REPLACE VIEW rv.bv_customer_mdm__ekb AS
WITH
    personal AS (
        SELECT DISTINCT ON (customer_hk)
            customer_hk, first_name, last_name, email, phone, birth_date,
            load_ts AS pii_seen_at
        FROM rv.sat_customer_personal__1c__ekb WHERE is_deleted = 0
        ORDER BY customer_hk, load_ts DESC
    ),
    loyalty AS (
        SELECT DISTINCT ON (customer_hk)
            customer_hk, loyalty_segment, loyalty_points, last_visit_at,
            load_ts AS loyalty_seen_at
        FROM rv.sat_customer_loyalty__bitrix__ekb WHERE is_deleted = 0
        ORDER BY customer_hk, load_ts DESC
    ),
    branch_hub AS (
        SELECT customer_hk, customer_bk FROM rv.hub_customer
        WHERE split_part(record_source, '__', 2) = 'ekb'
    )
SELECT
    h.customer_hk     AS customer_hk,
    h.customer_bk     AS customer_bk,
    'ekb'             AS branch,
    p.first_name      AS first_name,
    p.last_name       AS last_name,
    p.email           AS email,
    p.phone           AS phone,
    p.birth_date      AS birth_date,
    l.loyalty_segment AS loyalty_segment,
    l.loyalty_points  AS loyalty_points,
    l.last_visit_at   AS last_visit_at,
    CASE WHEN p.customer_hk IS NOT NULL THEN '1c__ekb' END     AS pii_source,
    CASE WHEN l.customer_hk IS NOT NULL THEN 'bitrix__ekb' END AS loyalty_source,
    GREATEST(coalesce(p.pii_seen_at, '1970-01-01'::timestamp(3)),
             coalesce(l.loyalty_seen_at, '1970-01-01'::timestamp(3))) AS last_seen_at
FROM branch_hub h
LEFT JOIN personal p ON h.customer_hk = p.customer_hk
LEFT JOIN loyalty  l ON h.customer_hk = l.customer_hk;

CREATE OR REPLACE VIEW rv.bv_customer_mdm__dxb AS
WITH
    personal AS (
        SELECT DISTINCT ON (customer_hk)
            customer_hk, first_name, last_name, email, phone, birth_date,
            load_ts AS pii_seen_at
        FROM rv.sat_customer_personal__1c__dxb WHERE is_deleted = 0
        ORDER BY customer_hk, load_ts DESC
    ),
    branch_hub AS (
        SELECT customer_hk, customer_bk FROM rv.hub_customer
        WHERE split_part(record_source, '__', 2) = 'dxb'
    )
SELECT
    h.customer_hk        AS customer_hk,
    h.customer_bk        AS customer_bk,
    'dxb'                AS branch,
    p.first_name         AS first_name,
    p.last_name          AS last_name,
    p.email              AS email,
    p.phone              AS phone,
    p.birth_date         AS birth_date,
    NULL::text           AS loyalty_segment,
    NULL::numeric(18, 2) AS loyalty_points,
    NULL::timestamp(3)   AS last_visit_at,
    CASE WHEN p.customer_hk IS NOT NULL THEN '1c__dxb' END AS pii_source,
    NULL::text           AS loyalty_source,
    coalesce(p.pii_seen_at, '1970-01-01'::timestamp(3)) AS last_seen_at
FROM branch_hub h
LEFT JOIN personal p ON h.customer_hk = p.customer_hk;

CREATE OR REPLACE VIEW rv.bv_customer_mdm__ala AS
WITH
    personal AS (
        SELECT DISTINCT ON (customer_hk)
            customer_hk, first_name, last_name, email, phone, birth_date,
            load_ts AS pii_seen_at
        FROM rv.sat_customer_personal__1c__ala WHERE is_deleted = 0
        ORDER BY customer_hk, load_ts DESC
    ),
    branch_hub AS (
        SELECT customer_hk, customer_bk FROM rv.hub_customer
        WHERE split_part(record_source, '__', 2) = 'ala'
    )
SELECT
    h.customer_hk        AS customer_hk,
    h.customer_bk        AS customer_bk,
    'ala'                AS branch,
    p.first_name         AS first_name,
    p.last_name          AS last_name,
    p.email              AS email,
    p.phone              AS phone,
    p.birth_date         AS birth_date,
    NULL::text           AS loyalty_segment,
    NULL::numeric(18, 2) AS loyalty_points,
    NULL::timestamp(3)   AS last_visit_at,
    CASE WHEN p.customer_hk IS NOT NULL THEN '1c__ala' END AS pii_source,
    NULL::text           AS loyalty_source,
    coalesce(p.pii_seen_at, '1970-01-01'::timestamp(3)) AS last_seen_at
FROM branch_hub h
LEFT JOIN personal p ON h.customer_hk = p.customer_hk;
