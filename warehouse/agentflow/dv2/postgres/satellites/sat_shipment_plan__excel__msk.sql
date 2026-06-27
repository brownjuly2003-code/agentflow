/*
Purpose: Shipment plan data from logistics Excel files.
Sources: excel.
Branch context: per-branch logistics plan.
SCD2: yes.
Anonymization: hot.
record_source value: excel__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_shipment_plan__excel__msk (
    shipment_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'excel__msk',
    planned_ship_date DATE,
    planned_delivery_date DATE,
    route_code      TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (shipment_hk, load_ts)
);
