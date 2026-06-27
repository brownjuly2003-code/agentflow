-- DV2 raw-vault hubs, PostgreSQL dialect.
-- Hash key (BYTEA, 16-byte MD5) is the primary key; the business key carries a
-- btree index for lookups. Idempotent loads use INSERT ... ON CONFLICT (hk)
-- DO NOTHING. record_source format: {source_system}__{branch_code}.
-- Foreign keys to/from links are intentionally NOT enforced (Data Vault loads
-- arrive out of order and in parallel; integrity is by hash construction).

CREATE TABLE IF NOT EXISTS rv.hub_customer (
    customer_hk   BYTEA PRIMARY KEY,
    customer_bk   TEXT NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customer_bk ON rv.hub_customer (customer_bk);

CREATE TABLE IF NOT EXISTS rv.hub_employee (
    employee_hk   BYTEA PRIMARY KEY,
    employee_bk   TEXT NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_employee_bk ON rv.hub_employee (employee_bk);

CREATE TABLE IF NOT EXISTS rv.hub_marking_code (
    marking_code_hk BYTEA PRIMARY KEY,
    marking_code_bk TEXT NOT NULL,
    load_ts         TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_marking_code_bk ON rv.hub_marking_code (marking_code_bk);

CREATE TABLE IF NOT EXISTS rv.hub_order (
    order_hk      BYTEA PRIMARY KEY,
    order_bk      TEXT NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_bk ON rv.hub_order (order_bk);

CREATE TABLE IF NOT EXISTS rv.hub_product (
    product_hk    BYTEA PRIMARY KEY,
    product_bk    TEXT NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_bk ON rv.hub_product (product_bk);

CREATE TABLE IF NOT EXISTS rv.hub_shipment (
    shipment_hk   BYTEA PRIMARY KEY,
    shipment_bk   TEXT NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shipment_bk ON rv.hub_shipment (shipment_bk);

CREATE TABLE IF NOT EXISTS rv.hub_store (
    store_hk      BYTEA PRIMARY KEY,
    store_bk      TEXT NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_store_bk ON rv.hub_store (store_bk);

CREATE TABLE IF NOT EXISTS rv.hub_supplier (
    supplier_hk   BYTEA PRIMARY KEY,
    supplier_bk   TEXT NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_supplier_bk ON rv.hub_supplier (supplier_bk);
