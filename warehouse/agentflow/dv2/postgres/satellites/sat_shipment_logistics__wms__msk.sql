/*
Purpose: Physical shipment status from WMS.
Sources: wms.
Branch context: per-branch shipment context.
SCD2: yes.
Anonymization: hot.
record_source value: wms__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_shipment_logistics__wms__msk (
    shipment_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'wms__msk',
    shipment_status TEXT,
    carrier_name    TEXT,
    shipped_at      TIMESTAMP(3),
    delivered_at    TIMESTAMP(3),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (shipment_hk, load_ts)
);
