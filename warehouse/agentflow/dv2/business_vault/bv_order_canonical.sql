/*
Purpose: Canonical order row joining Bitrix order header, 1C pricing, and
         (where present) Wildberries marketplace state, attributed to a
         customer + branch.
Layer:   Business Vault (read-only view over raw_vault).
Branch:  all (rows carry the branch column derived from hub_order.record_source).
Conflict policy:
  - Order header (status / channel / order_date / total) — Bitrix wins,
    1C-only orders fall through with NULL header until 1C order sat lands.
  - Pricing (subtotal / discount / tax / shipping) — 1C wins (accounting
    source of truth).
  - Marketplace (wb_status / wb_commission / return_window) — Wildberries
    where the order was sourced through the marketplace.
SCD effective row:
  - argMax(.., load_ts) collapses SCD2 satellite history to the most recent
    state. Point-in-time travel lives in a separate `bv_order_canonical_pit`
    object (not implemented in the demo).
*/
CREATE OR REPLACE VIEW rv.bv_order_canonical AS
WITH
    header AS (
        SELECT
            order_hk,
            argMax(order_date, load_ts)    AS order_date,
            argMax(channel, load_ts)       AS channel,
            argMax(order_status, load_ts)  AS order_status,
            argMax(total_amount, load_ts)  AS total_amount
        FROM rv.sat_order_header__bitrix__msk
        WHERE is_deleted = 0
        GROUP BY order_hk
    ),
    pricing AS (
        SELECT
            order_hk,
            argMax(subtotal_amount, load_ts)  AS subtotal_amount,
            argMax(discount_amount, load_ts)  AS discount_amount,
            argMax(tax_amount, load_ts)       AS tax_amount,
            argMax(shipping_cost, load_ts)    AS shipping_cost
        FROM rv.sat_order_pricing__1c__msk
        WHERE is_deleted = 0
        GROUP BY order_hk
    ),
    marketplace AS (
        SELECT
            order_hk,
            argMax(wb_status, load_ts)        AS wb_status,
            argMax(wb_commission, load_ts)    AS wb_commission,
            argMax(return_window_until, load_ts) AS wb_return_window_until
        FROM rv.sat_order_marketplace__wb__msk
        WHERE is_deleted = 0
        GROUP BY order_hk
    ),
    order_branch AS (
        SELECT
            order_hk,
            order_bk,
            splitByString('__', record_source)[2] AS branch
        FROM rv.hub_order
    ),
    order_customer AS (
        SELECT order_hk, argMax(customer_hk, load_ts) AS customer_hk
        FROM rv.lnk_order_customer
        GROUP BY order_hk
    ),
    order_store AS (
        SELECT order_hk, argMax(store_hk, load_ts) AS store_hk
        FROM rv.lnk_order_store
        GROUP BY order_hk
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
    if(h.order_hk != toFixedString('', 16), 'bitrix__msk', NULL) AS header_source,
    if(p.order_hk != toFixedString('', 16), '1c__msk', NULL)     AS pricing_source,
    if(m.order_hk != toFixedString('', 16), 'wb__msk', NULL)     AS marketplace_source
FROM order_branch o
LEFT JOIN header      h ON o.order_hk = h.order_hk
LEFT JOIN pricing     p ON o.order_hk = p.order_hk
LEFT JOIN marketplace m ON o.order_hk = m.order_hk
LEFT JOIN order_customer oc ON o.order_hk = oc.order_hk
LEFT JOIN order_store    os ON o.order_hk = os.order_hk;
