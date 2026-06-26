-- DV2 raw-vault links, PostgreSQL dialect.
-- link_hk (BYTEA, 16-byte MD5 of the member hash keys) is the primary key;
-- each member hash key carries a btree index so the multi-way LEFT JOINs in
-- the business vault are index-driven (the join-heavy reconstruction that
-- motivated moving the vault off ClickHouse onto PostgreSQL).

CREATE TABLE IF NOT EXISTS rv.lnk_order_customer (
    link_hk       BYTEA PRIMARY KEY,
    order_hk      BYTEA NOT NULL,
    customer_hk   BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnk_order_customer_order ON rv.lnk_order_customer (order_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_order_customer_customer ON rv.lnk_order_customer (customer_hk);

CREATE TABLE IF NOT EXISTS rv.lnk_order_employee (
    link_hk       BYTEA PRIMARY KEY,
    order_hk      BYTEA NOT NULL,
    employee_hk   BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnk_order_employee_order ON rv.lnk_order_employee (order_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_order_employee_employee ON rv.lnk_order_employee (employee_hk);

CREATE TABLE IF NOT EXISTS rv.lnk_order_product (
    link_hk       BYTEA PRIMARY KEY,
    order_hk      BYTEA NOT NULL,
    product_hk    BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnk_order_product_order ON rv.lnk_order_product (order_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_order_product_product ON rv.lnk_order_product (product_hk);

CREATE TABLE IF NOT EXISTS rv.lnk_order_shipment (
    link_hk       BYTEA PRIMARY KEY,
    order_hk      BYTEA NOT NULL,
    shipment_hk   BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnk_order_shipment_order ON rv.lnk_order_shipment (order_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_order_shipment_shipment ON rv.lnk_order_shipment (shipment_hk);

CREATE TABLE IF NOT EXISTS rv.lnk_order_store (
    link_hk       BYTEA PRIMARY KEY,
    order_hk      BYTEA NOT NULL,
    store_hk      BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnk_order_store_order ON rv.lnk_order_store (order_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_order_store_store ON rv.lnk_order_store (store_hk);

CREATE TABLE IF NOT EXISTS rv.lnk_product_marking (
    link_hk         BYTEA PRIMARY KEY,
    product_hk      BYTEA NOT NULL,
    marking_code_hk BYTEA NOT NULL,
    load_ts         TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnk_product_marking_product ON rv.lnk_product_marking (product_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_product_marking_marking ON rv.lnk_product_marking (marking_code_hk);

CREATE TABLE IF NOT EXISTS rv.lnk_product_supplier (
    link_hk       BYTEA PRIMARY KEY,
    product_hk    BYTEA NOT NULL,
    supplier_hk   BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnk_product_supplier_product ON rv.lnk_product_supplier (product_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_product_supplier_supplier ON rv.lnk_product_supplier (supplier_hk);

CREATE TABLE IF NOT EXISTS rv.lnk_shipment_store (
    link_hk              BYTEA PRIMARY KEY,
    shipment_hk          BYTEA NOT NULL,
    origin_store_hk      BYTEA NOT NULL,
    destination_store_hk BYTEA NOT NULL,
    load_ts              TIMESTAMP(3) NOT NULL DEFAULT now(),
    record_source        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnk_shipment_store_shipment ON rv.lnk_shipment_store (shipment_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_shipment_store_origin ON rv.lnk_shipment_store (origin_store_hk);
CREATE INDEX IF NOT EXISTS idx_lnk_shipment_store_destination ON rv.lnk_shipment_store (destination_store_hk);
