/*
Purpose: Marking-code scan state from WMS.
Sources: wms.
Branch context: global warehouse traceability.
SCD2: yes.
Anonymization: hot.
record_source value: wms__global
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_marking_code_wms__wms__global (
    marking_code_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'wms__global',
    last_scan_at    TIMESTAMP(3),
    last_scan_location TEXT,
    scan_status     TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (marking_code_hk, load_ts)
);
