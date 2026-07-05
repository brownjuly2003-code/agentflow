-- Hot-tier OLTP seed for the DV2.0 demo (own-brand kitchen-appliance
-- importer legend — see synthetic_seed.sql for the full customer/order
-- numbering this small sample mirrors at hot-tier scale).
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
-- Channels / statuses / amounts mirror satellite_seed.sql (generator-spec.md
-- §1/§2): msk carries the marketplace-dominant mix (marketplace 1.5k-3k, d2c
-- 2k-5k, b2b 30k-80k ₽ net-of-VAT), status ladder pending/confirmed/shipped/
-- delivered/cancelled at 8/10/12/62/8. Amounts stay clear of the 10k-25k
-- bimodality dead-zone (§12 #4).
INSERT INTO ops_msk.customers (customer_id, first_name, last_name, email, phone)
SELECT
    'CUST-MSK-' || lpad(n::text, 4, '0'),
    (ARRAY['Anna','Boris','Dasha','Egor','Fedor','Galya','Ivan','Kira','Lena','Mark'])[(n % 10) + 1],
    (ARRAY['Ivanov','Petrov','Sidorov','Smirnov','Volkov','Orlov','Lebedev','Sokolov'])[(n % 8) + 1],
    'oltp' || n::text || '@example.test',
    '+7495' || lpad((n * 137 % 10000000)::text, 7, '0')
FROM generate_series(1, 50) AS n
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO ops_msk.orders (order_id, customer_id, order_date, channel, order_status, total_amount)
SELECT
    'OLTP-MSK-' || lpad(n::text, 6, '0'),
    'CUST-MSK-' || lpad(((n % 50) + 1)::text, 4, '0'),
    now() - (n || ' hour')::interval,
    CASE
        WHEN n <= 186 THEN 'marketplace'
        WHEN n <= 193 THEN 'd2c'
        ELSE 'b2b'
    END,
    CASE
        WHEN n % 100 < 8  THEN 'pending'
        WHEN n % 100 < 18 THEN 'confirmed'
        WHEN n % 100 < 30 THEN 'shipped'
        WHEN n % 100 < 92 THEN 'delivered'
        ELSE 'cancelled'
    END,
    CASE
        WHEN n <= 186 THEN (1500 + (n * 17) % 1501)::numeric(18, 2)   -- marketplace 1.5k-3.0k
        WHEN n <= 193 THEN (2000 + (n * 23) % 3001)::numeric(18, 2)   -- d2c 2.0k-5.0k
        ELSE (30000 + (n * 137) % 50001)::numeric(18, 2)             -- b2b msk 30k-80k
    END
FROM generate_series(1, 200) AS n
ON CONFLICT (order_id) DO NOTHING;

-- ============ Seed: 20 dxb customers + 80 dxb orders ============
-- dxb is the b2b re-export branch (generator-spec.md §1: no marketplace/D2C
-- volume). All orders are 'b2b'; amounts follow the export-pallet band
-- (60k-130k ₽ net, mirrors satellite_seed_all_branches.sql), well above the
-- 10k-25k dead-zone.
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
    'b2b',
    CASE
        WHEN n % 100 < 8  THEN 'pending'
        WHEN n % 100 < 18 THEN 'confirmed'
        WHEN n % 100 < 30 THEN 'shipped'
        WHEN n % 100 < 92 THEN 'delivered'
        ELSE 'cancelled'
    END,
    (60000 + (n * 191) % 70001)::numeric(18, 2)   -- b2b dxb export pallets 60k-130k
FROM generate_series(1, 80) AS n
ON CONFLICT (order_id) DO NOTHING;
