-- DV2 raw vault, PostgreSQL dialect.
-- The vault lives in the `rv` schema (the ClickHouse build used an `rv`
-- database; on PostgreSQL it is a schema). See postgres/README.md for the
-- ClickHouse -> PostgreSQL migration rationale and apply order.
CREATE SCHEMA IF NOT EXISTS rv;
