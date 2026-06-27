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
