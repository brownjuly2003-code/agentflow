-- Hot-tier OLTP seed for the DV2.0 demo.
-- Lives in Postgres 17, per-branch schema layout (ops_<branch>) so the
-- CDC bridge described in docs/dv2-multi-branch/architecture.md can route
-- straight by schema name. Each schema gets its own customers + orders table.

-- ============ MSK schema ============
CREATE SCHEMA IF NOT EXISTS ops_msk;

CREATE TABLE IF NOT EXISTS ops_msk.customers (
    customer_id    text PRIMARY KEY,
    first_name     text NOT NULL,
    last_name      text NOT NULL,
    email          text,
    phone          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops_msk.orders (
    order_id       text PRIMARY KEY,
    customer_id    text REFERENCES ops_msk.customers(customer_id),
    order_date     timestamptz NOT NULL DEFAULT now(),
    channel        text NOT NULL,
    order_status   text NOT NULL,
    total_amount   numeric(18, 2) NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- ============ DXB schema ============
CREATE SCHEMA IF NOT EXISTS ops_dxb;

CREATE TABLE IF NOT EXISTS ops_dxb.customers (
    customer_id    text PRIMARY KEY,
    first_name     text NOT NULL,
    last_name      text NOT NULL,
    email          text,
    phone          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops_dxb.orders (
    order_id       text PRIMARY KEY,
    customer_id    text REFERENCES ops_dxb.customers(customer_id),
    order_date     timestamptz NOT NULL DEFAULT now(),
    channel        text NOT NULL,
    order_status   text NOT NULL,
    total_amount   numeric(18, 2) NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- ============ Seed: 50 msk customers + 200 msk orders ============
INSERT INTO ops_msk.customers (customer_id, first_name, last_name, email, phone)
SELECT
    'CUST-MSK-' || lpad(n::text, 4, '0'),
    (ARRAY['Anna','Boris','Dasha','Egor','Fedor','Galya','Ivan','Kira','Lena','Mark'])[(n % 10) + 1],
    (ARRAY['Ivanov','Petrov','Sidorov','Smirnov','Volkov','Orlov','Lebedev','Sokolov'])[(n % 8) + 1],
    'oltp' || n::text || '@example.test',
    '+7916' || lpad((n * 137 % 10000000)::text, 7, '0')
FROM generate_series(1, 50) AS n
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO ops_msk.orders (order_id, customer_id, order_date, channel, order_status, total_amount)
SELECT
    'OLTP-MSK-' || lpad(n::text, 6, '0'),
    'CUST-MSK-' || lpad(((n % 50) + 1)::text, 4, '0'),
    now() - (n || ' hour')::interval,
    (ARRAY['web','mobile','retail','call-center'])[(n % 4) + 1],
    (ARRAY['new','paid','shipped'])[(n % 3) + 1],
    (500 + (n * 31) % 24500)::numeric(18, 2)
FROM generate_series(1, 200) AS n
ON CONFLICT (order_id) DO NOTHING;

-- ============ Seed: 20 dxb customers + 80 dxb orders ============
INSERT INTO ops_dxb.customers (customer_id, first_name, last_name, email, phone)
SELECT
    'CUST-DXB-' || lpad(n::text, 4, '0'),
    (ARRAY['Aisha','Khalid','Layla','Omar','Sara','Yusuf','Mariam','Ahmed'])[(n % 8) + 1],
    (ARRAY['Al-Sayed','Al-Maktoum','Hassan','Rashid','Hamdan','Saleh'])[(n % 6) + 1],
    'oltp' || n::text || '@example.ae',
    '+9715' || lpad((n * 137 % 10000000)::text, 7, '0')
FROM generate_series(1, 20) AS n
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO ops_dxb.orders (order_id, customer_id, order_date, channel, order_status, total_amount)
SELECT
    'OLTP-DXB-' || lpad(n::text, 6, '0'),
    'CUST-DXB-' || lpad(((n % 20) + 1)::text, 4, '0'),
    now() - (n || ' hour')::interval,
    (ARRAY['web','mobile','retail'])[(n % 3) + 1],
    (ARRAY['new','paid','shipped'])[(n % 3) + 1],
    (500 + (n * 31) % 24500)::numeric(18, 2)
FROM generate_series(1, 80) AS n
ON CONFLICT (order_id) DO NOTHING;
