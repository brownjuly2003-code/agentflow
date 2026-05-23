/*
Purpose: Raw vault link for shipment origin and destination stores.
Sources: wms, excel.
Branch context: per-branch logistics attribution.
SCD2: no.
Anonymization: hot logistics link.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.lnk_shipment_store (
    link_hk              FixedString(16),
    shipment_hk          FixedString(16),
    origin_store_hk      FixedString(16),
    destination_store_hk FixedString(16),
    load_ts              DateTime64(3) DEFAULT now64(3),
    record_source        LowCardinality(String)
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (link_hk);
