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
    countIf(order_status = 'returned')                  AS returned_orders,
    round(countIf(order_status = 'returned') * 1.0 /
          count(), 4)                                   AS return_rate,
    sumIf(toFloat64(total_amount),
          order_status = 'returned')                    AS returned_value,
    sumIf(toFloat64(tax_amount),
          order_status = 'returned')                    AS returned_tax_unrecovered
FROM {{ source('rv', 'bv_order_canonical') }}
WHERE order_date IS NOT NULL
  AND channel IS NOT NULL
GROUP BY branch, channel, week
