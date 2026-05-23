-- ClickHouse-side bridge to the hot tier (Postgres OLTP).
-- Uses ClickHouse 25.x `PostgreSQL()` table engine, which keeps the warehouse
-- as a passive consumer — no Postgres replication slot or Debezium
-- dependency to operate the demo. Each table is a live read-through of
-- the corresponding ops_<branch>.<entity> table.
--
-- In production a CDC bridge (PeerDB, Debezium, or Postgres logical
-- replication consumed by a ClickHouse PeerDB connector) would push
-- changes asynchronously; the `PostgreSQL()` engine path used here is
-- the simpler, idempotent demo equivalent.

CREATE DATABASE IF NOT EXISTS oltp_live;

-- ============ MSK live mirrors ============
CREATE TABLE IF NOT EXISTS oltp_live.msk_customers
(
    customer_id  String,
    first_name   String,
    last_name    String,
    email        Nullable(String),
    phone        Nullable(String),
    created_at   DateTime64(6, 'UTC'),
    updated_at   DateTime64(6, 'UTC')
) ENGINE = PostgreSQL(
    'postgres:5432', 'ops', 'customers', 'ops', 'demo', 'ops_msk'
);

CREATE TABLE IF NOT EXISTS oltp_live.msk_orders
(
    order_id      String,
    customer_id   String,
    order_date    DateTime64(6, 'UTC'),
    channel       String,
    order_status  String,
    total_amount  Decimal(18, 2),
    updated_at    DateTime64(6, 'UTC')
) ENGINE = PostgreSQL(
    'postgres:5432', 'ops', 'orders', 'ops', 'demo', 'ops_msk'
);

-- ============ DXB live mirrors ============
CREATE TABLE IF NOT EXISTS oltp_live.dxb_customers
(
    customer_id  String,
    first_name   String,
    last_name    String,
    email        Nullable(String),
    phone        Nullable(String),
    created_at   DateTime64(6, 'UTC'),
    updated_at   DateTime64(6, 'UTC')
) ENGINE = PostgreSQL(
    'postgres:5432', 'ops', 'customers', 'ops', 'demo', 'ops_dxb'
);

CREATE TABLE IF NOT EXISTS oltp_live.dxb_orders
(
    order_id      String,
    customer_id   String,
    order_date    DateTime64(6, 'UTC'),
    channel       String,
    order_status  String,
    total_amount  Decimal(18, 2),
    updated_at    DateTime64(6, 'UTC')
) ENGINE = PostgreSQL(
    'postgres:5432', 'ops', 'orders', 'ops', 'demo', 'ops_dxb'
);
