/*
Purpose: Product marketplace listing state from Wildberries.
Sources: wb.
Branch context: marketplace listing for Moscow fulfillment.
SCD2: yes.
Anonymization: hot.
record_source value: wb__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_marketplace__wb__msk (
    product_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'wb__msk',
    wb_id           TEXT,
    wb_price        NUMERIC(18, 2),
    wb_status       TEXT,
    wb_rating       NUMERIC(5, 2),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (product_hk, load_ts)
);
