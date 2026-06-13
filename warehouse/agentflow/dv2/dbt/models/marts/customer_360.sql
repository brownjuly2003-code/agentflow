{#
  customer_bk first in the sort key: the mart's serving pattern is a point
  lookup by business key (load-test 03_customer360_point). At X5 scale the
  old (branch, customer_hk) key meant every bk lookup full-scanned the mart:
  p99 250-470 ms vs the 200 ms point budget.
#}
{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(customer_bk, branch)',
        settings={'index_granularity': 1024}
    )
}}

WITH customers AS (
    SELECT customer_hk, customer_bk, branch, first_name, last_name, email,
           loyalty_segment, loyalty_points, last_visit_at, pii_source, loyalty_source
    FROM {{ source('rv', 'bv_customer_mdm__msk') }}
    UNION ALL
    SELECT customer_hk, customer_bk, branch, first_name, last_name, email,
           loyalty_segment, loyalty_points, last_visit_at, pii_source, loyalty_source
    FROM {{ source('rv', 'bv_customer_mdm__spb') }}
    UNION ALL
    SELECT customer_hk, customer_bk, branch, first_name, last_name, email,
           loyalty_segment, loyalty_points, last_visit_at, pii_source, loyalty_source
    FROM {{ source('rv', 'bv_customer_mdm__ekb') }}
    UNION ALL
    SELECT customer_hk, customer_bk, branch, first_name, last_name, email,
           loyalty_segment, loyalty_points, last_visit_at, pii_source, loyalty_source
    FROM {{ source('rv', 'bv_customer_mdm__dxb') }}
    UNION ALL
    SELECT customer_hk, customer_bk, branch, first_name, last_name, email,
           loyalty_segment, loyalty_points, last_visit_at, pii_source, loyalty_source
    FROM {{ source('rv', 'bv_customer_mdm__ala') }}
),
order_agg AS (
    SELECT
        customer_hk,
        branch,
        count()                                      AS order_count,
        sum(toFloat64(total_amount))                 AS lifetime_value,
        min(order_date)                              AS first_order_dt,
        max(order_date)                              AS last_order_dt,
        countIf(order_status = 'returned')           AS returned_orders,
        sumIf(toFloat64(total_amount),
              order_status = 'returned')             AS returned_value
    FROM {{ source('rv', 'bv_order_canonical_mat') }}
    WHERE customer_hk != toFixedString('', 16)
    GROUP BY customer_hk, branch
)
SELECT
    c.customer_hk                                    AS customer_hk,
    c.customer_bk                                    AS customer_bk,
    c.branch                                         AS branch,
    c.first_name                                     AS first_name,
    c.last_name                                      AS last_name,
    c.email                                          AS email,
    c.loyalty_segment                                AS loyalty_segment,
    c.loyalty_points                                 AS loyalty_points,
    c.last_visit_at                                  AS last_visit_at,
    c.pii_source                                     AS pii_source,
    c.loyalty_source                                 AS loyalty_source,
    coalesce(o.order_count, 0)                       AS order_count,
    coalesce(o.lifetime_value, 0.0)                  AS lifetime_value,
    o.first_order_dt                                 AS first_order_dt,
    o.last_order_dt                                  AS last_order_dt,
    coalesce(o.returned_orders, 0)                   AS returned_orders,
    coalesce(o.returned_value, 0.0)                  AS returned_value,
    if(coalesce(o.order_count, 0) > 0,
       toFloat64(o.returned_orders) / o.order_count,
       0.0)                                          AS return_rate
FROM customers c
LEFT JOIN order_agg o
  ON c.customer_hk = o.customer_hk
 AND c.branch = o.branch
