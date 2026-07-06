/*
Purpose: Materialized snapshot of rv.bv_order_canonical (same columns, same
         row semantics) so the dbt marts read a plain MergeTree table instead
         of re-computing the argMax view inside every mart build.
Why:     At large raw-vault volumes one full scan of the argMax view needs
         >4 GiB — over the 3 GiB per-query cap on the 8 GB demo host (four
         OOM'd dbt runs, 2026-06-06, against a retired at-scale capture —
         see git history of docs/dv2-multi-branch/load-test-baseline.md;
         "plan B" for that OOM).
         Materializing once per branch keeps every single INSERT bounded.
Layer:   Business Vault (derived, rebuildable from raw_vault at any time).
Load:    load_bv_order_canonical_mat.sh — per-branch staged INSERT SELECTs
         (msk/spb additionally hash-sliced in two), branch = partition, so a
         failed branch is retried with ALTER TABLE ... DROP PARTITION.
Refresh: NOT auto-updated. Re-run the load script after raw_vault changes
         (same contract as the dbt-materialized marts downstream).
*/
CREATE TABLE IF NOT EXISTS rv.bv_order_canonical_mat
(
    order_hk                FixedString(16),
    order_bk                String,
    branch                  String,
    customer_hk             FixedString(16),
    store_hk                FixedString(16),
    order_date              DateTime64(3),
    channel                 String,
    order_status            String,
    total_amount            Decimal(18, 2),
    subtotal_amount         Decimal(18, 2),
    discount_amount         Decimal(18, 2),
    tax_amount              Decimal(18, 2),
    shipping_cost           Decimal(18, 2),
    wb_status               String,
    wb_commission           Decimal(18, 2),
    wb_return_window_until  Nullable(Date),
    header_source           Nullable(String),
    pricing_source          Nullable(String),
    marketplace_source      Nullable(String)
)
ENGINE = MergeTree
PARTITION BY branch
ORDER BY (branch, order_bk);
