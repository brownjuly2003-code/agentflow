/*
Purpose: Product stock snapshot from WMS.
Sources: wms.
Branch context: branch warehouse stock.
SCD2: yes.
Anonymization: hot.
record_source value: wms__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_stock__wms__msk (
    product_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'wms__msk',
    qty_on_hand     NUMERIC(18, 3),
    qty_reserved    NUMERIC(18, 3),
    qty_available   NUMERIC(18, 3),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (product_hk, load_ts)
);
