-- Hot -> warm promotion, PostgreSQL-native.
--
-- The raw vault now lives on PostgreSQL (see dv2/postgres/README.md), the same
-- engine as this OLTP hot tier. So the ClickHouse `PostgreSQL()` bridge that the
-- ClickHouse-era promotion needed (oltp_live.*) collapses: promotion is a plain
-- in-database INSERT ... SELECT straight from the ops_<branch> schemas into rv.*.
-- This is the "PostgreSQL is the common root from which both CDC->Kafka->serving
-- and the vault are fed" point made concrete.
--
-- Translation from the ClickHouse variant (promote_to_raw_vault.sql):
--   MD5(x) (FixedString(16))      -> decode(md5(x), 'hex')  (BYTEA, join-identical)
--   now64(3)                      -> localtimestamp(3)       (one txn-stable load_ts)
--   concat(a, '|', b)             -> a || '|' || b
--   FROM oltp_live.<branch>_<tbl> -> FROM ops_<branch>.<tbl> (no bridge)
--
-- Idempotency: hubs/links collide on their BYTEA primary key
-- (ON CONFLICT DO NOTHING); satellites insert a version only when the
-- (hash key, hash_diff) pair is not already present, so a re-run is a no-op.
-- hash_diff mirrors the ClickHouse pull variant: a constant per-entity tag (the
-- `PostgreSQL()` snapshot is treated as append-only — no change/tombstone
-- capture), so each OLTP entity lands exactly one satellite version.
--
-- record_source = pg_ops__<branch> so the business vault's
-- split_part(record_source, '__', 2) extracts the branch.
--
-- Apply (single-node Mac demo, after seed.sql and dv2/postgres/apply.sh):
--   PGHOST=localhost PGUSER=agentflow PGDATABASE=agentflow \
--       psql -v ON_ERROR_STOP=1 -f promote_to_raw_vault_pg.sql

BEGIN;

-- ============ MSK: hub customer + personal satellite ============
INSERT INTO rv.hub_customer (customer_hk, customer_bk, load_ts, record_source)
SELECT decode(md5(customer_id), 'hex'), customer_id, localtimestamp(3), 'pg_ops__msk'
FROM ops_msk.customers
ON CONFLICT DO NOTHING;

INSERT INTO rv.sat_customer_personal__1c__msk
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    decode(md5(c.customer_id), 'hex'),
    localtimestamp(3),
    decode(md5(c.customer_id || '|pg-oltp|v1'), 'hex'),
    'pg_ops__msk',
    c.first_name,
    c.last_name,
    coalesce(c.email, ''),
    coalesce(c.phone, ''),
    NULL,
    TRUE,
    0
FROM ops_msk.customers c
WHERE NOT EXISTS (
    SELECT 1 FROM rv.sat_customer_personal__1c__msk e
    WHERE e.customer_hk = decode(md5(c.customer_id), 'hex')
      AND e.hash_diff = decode(md5(c.customer_id || '|pg-oltp|v1'), 'hex')
);

-- ============ MSK: hub order + header satellite + order<->customer link ============
INSERT INTO rv.hub_order (order_hk, order_bk, load_ts, record_source)
SELECT decode(md5(order_id), 'hex'), order_id, localtimestamp(3), 'pg_ops__msk'
FROM ops_msk.orders
ON CONFLICT DO NOTHING;

INSERT INTO rv.sat_order_header__bitrix__msk
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    decode(md5(o.order_id), 'hex'),
    localtimestamp(3),
    decode(md5(o.order_id || '|pg-hdr|v1'), 'hex'),
    'pg_ops__msk',
    o.order_date::timestamp(3),
    o.channel,
    o.order_status,
    o.total_amount,
    0
FROM ops_msk.orders o
WHERE NOT EXISTS (
    SELECT 1 FROM rv.sat_order_header__bitrix__msk e
    WHERE e.order_hk = decode(md5(o.order_id), 'hex')
      AND e.hash_diff = decode(md5(o.order_id || '|pg-hdr|v1'), 'hex')
);

INSERT INTO rv.lnk_order_customer (link_hk, order_hk, customer_hk, load_ts, record_source)
SELECT
    decode(md5(order_id || '|' || customer_id), 'hex'),
    decode(md5(order_id), 'hex'),
    decode(md5(customer_id), 'hex'),
    localtimestamp(3),
    'pg_ops__msk'
FROM ops_msk.orders
ON CONFLICT DO NOTHING;

-- ============ DXB: hub customer + personal satellite ============
INSERT INTO rv.hub_customer (customer_hk, customer_bk, load_ts, record_source)
SELECT decode(md5(customer_id), 'hex'), customer_id, localtimestamp(3), 'pg_ops__dxb'
FROM ops_dxb.customers
ON CONFLICT DO NOTHING;

INSERT INTO rv.sat_customer_personal__1c__dxb
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    decode(md5(c.customer_id), 'hex'),
    localtimestamp(3),
    decode(md5(c.customer_id || '|pg-oltp|v1'), 'hex'),
    'pg_ops__dxb',
    c.first_name,
    c.last_name,
    coalesce(c.email, ''),
    coalesce(c.phone, ''),
    NULL,
    TRUE,
    0
FROM ops_dxb.customers c
WHERE NOT EXISTS (
    SELECT 1 FROM rv.sat_customer_personal__1c__dxb e
    WHERE e.customer_hk = decode(md5(c.customer_id), 'hex')
      AND e.hash_diff = decode(md5(c.customer_id || '|pg-oltp|v1'), 'hex')
);

-- ============ DXB: hub order + header satellite + order<->customer link ============
INSERT INTO rv.hub_order (order_hk, order_bk, load_ts, record_source)
SELECT decode(md5(order_id), 'hex'), order_id, localtimestamp(3), 'pg_ops__dxb'
FROM ops_dxb.orders
ON CONFLICT DO NOTHING;

INSERT INTO rv.sat_order_header__bitrix__dxb
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    decode(md5(o.order_id), 'hex'),
    localtimestamp(3),
    decode(md5(o.order_id || '|pg-hdr|v1'), 'hex'),
    'pg_ops__dxb',
    o.order_date::timestamp(3),
    o.channel,
    o.order_status,
    o.total_amount,
    0
FROM ops_dxb.orders o
WHERE NOT EXISTS (
    SELECT 1 FROM rv.sat_order_header__bitrix__dxb e
    WHERE e.order_hk = decode(md5(o.order_id), 'hex')
      AND e.hash_diff = decode(md5(o.order_id || '|pg-hdr|v1'), 'hex')
);

INSERT INTO rv.lnk_order_customer (link_hk, order_hk, customer_hk, load_ts, record_source)
SELECT
    decode(md5(order_id || '|' || customer_id), 'hex'),
    decode(md5(order_id), 'hex'),
    decode(md5(customer_id), 'hex'),
    localtimestamp(3),
    'pg_ops__dxb'
FROM ops_dxb.orders
ON CONFLICT DO NOTHING;

COMMIT;
