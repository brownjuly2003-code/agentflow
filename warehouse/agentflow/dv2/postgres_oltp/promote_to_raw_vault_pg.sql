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
-- SCD2 change capture: hubs/links collide on their BYTEA primary key
-- (ON CONFLICT DO NOTHING). Satellites compute hash_diff over the *descriptive*
-- columns (status/amount/date/channel for the order header; name/email/phone for
-- the customer) and insert a new version only when that hash_diff differs from
-- the *current* (latest load_ts) version for the hash key. So a re-run with no
-- change is a no-op, but a changed order (e.g. pending -> shipped) or customer
-- correctly lands a new satellite version — which the LISTEN/NOTIFY freshness
-- listener that runs this promotion then surfaces. (A constant per-entity tag,
-- the old behaviour, silently dropped every UPDATE — see audit_28_06_26.md #9.)
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
    decode(md5(concat_ws('|', c.first_name, c.last_name, coalesce(c.email, ''), coalesce(c.phone, ''))), 'hex'),
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
      AND e.hash_diff = decode(md5(concat_ws('|', c.first_name, c.last_name, coalesce(c.email, ''), coalesce(c.phone, ''))), 'hex')
      AND e.load_ts = (
          SELECT max(e2.load_ts) FROM rv.sat_customer_personal__1c__msk e2
          WHERE e2.customer_hk = e.customer_hk
      )
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
    decode(md5(concat_ws('|', o.order_date::timestamp(3)::text, o.channel, o.order_status, o.total_amount::text)), 'hex'),
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
      AND e.hash_diff = decode(md5(concat_ws('|', o.order_date::timestamp(3)::text, o.channel, o.order_status, o.total_amount::text)), 'hex')
      AND e.load_ts = (
          SELECT max(e2.load_ts) FROM rv.sat_order_header__bitrix__msk e2
          WHERE e2.order_hk = e.order_hk
      )
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
    decode(md5(concat_ws('|', c.first_name, c.last_name, coalesce(c.email, ''), coalesce(c.phone, ''))), 'hex'),
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
      AND e.hash_diff = decode(md5(concat_ws('|', c.first_name, c.last_name, coalesce(c.email, ''), coalesce(c.phone, ''))), 'hex')
      AND e.load_ts = (
          SELECT max(e2.load_ts) FROM rv.sat_customer_personal__1c__dxb e2
          WHERE e2.customer_hk = e.customer_hk
      )
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
    decode(md5(concat_ws('|', o.order_date::timestamp(3)::text, o.channel, o.order_status, o.total_amount::text)), 'hex'),
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
      AND e.hash_diff = decode(md5(concat_ws('|', o.order_date::timestamp(3)::text, o.channel, o.order_status, o.total_amount::text)), 'hex')
      AND e.load_ts = (
          SELECT max(e2.load_ts) FROM rv.sat_order_header__bitrix__dxb e2
          WHERE e2.order_hk = e.order_hk
      )
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
