/*
Purpose: Wildberries order lifecycle and commission state.
Sources: wb.
Branch context: marketplace order state.
SCD2: yes.
Anonymization: hot.
record_source value: wb__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_order_marketplace__wb__msk (
    order_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'wb__msk',
    wb_status       TEXT,
    wb_commission   NUMERIC(18, 2),
    return_window_until DATE,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (order_hk, load_ts)
);
