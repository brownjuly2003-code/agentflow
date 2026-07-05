{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(branch, month)'
    )
}}

SELECT
    branch                                            AS branch,
    toStartOfMonth(order_date)                        AS month,
    count()                                           AS orders,
    sum(toFloat64(total_amount))                      AS gross_revenue,
    sum(toFloat64(tax_amount))                        AS tax_collected,
    sum(toFloat64(subtotal_amount))                   AS net_revenue,
    sum(toFloat64(discount_amount))                   AS discounts,
    sum(toFloat64(shipping_cost))                     AS shipping,
    -- The legend has no dedicated 'returned' status (§2 vocabulary is
    -- pending/confirmed/shipped/delivered/cancelled). Its terminal-negative
    -- bucket 'cancelled' carries both cancellations and marketplace returns
    -- (§2 "cancel/return allowance"; satellite_seed.sql — "marketplace cancels
    -- dominate the last bucket"), so returns are measured off 'cancelled'.
    countIf(order_status = 'cancelled')               AS returned_orders,
    sumIf(toFloat64(total_amount),
          order_status = 'cancelled')                 AS returned_value,
    round(sum(toFloat64(tax_amount)) /
          nullIf(sum(toFloat64(subtotal_amount)), 0),
          4)                                          AS effective_tax_rate
FROM {{ source('rv', 'bv_order_canonical_mat') }}
WHERE order_date IS NOT NULL
  AND subtotal_amount IS NOT NULL
GROUP BY branch, month
