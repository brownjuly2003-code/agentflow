{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(branch, channel, week)'
    )
}}

SELECT
    branch                                              AS branch,
    channel                                             AS channel,
    toStartOfWeek(order_date)                           AS week,
    count()                                             AS orders,
    -- Returns are measured off the 'cancelled' bucket: the legend has no
    -- dedicated 'returned' status (§2), and its terminal-negative bucket folds
    -- cancellations and marketplace returns together (§2 "cancel/return
    -- allowance"; satellite_seed.sql — "marketplace cancels dominate").
    countIf(order_status = 'cancelled')                 AS returned_orders,
    round(countIf(order_status = 'cancelled') * 1.0 /
          count(), 4)                                   AS return_rate,
    sumIf(toFloat64(total_amount),
          order_status = 'cancelled')                   AS returned_value,
    sumIf(toFloat64(tax_amount),
          order_status = 'cancelled')                   AS returned_tax_unrecovered
FROM {{ source('rv', 'bv_order_canonical_mat') }}
WHERE order_date IS NOT NULL
  AND channel IS NOT NULL
GROUP BY branch, channel, week
