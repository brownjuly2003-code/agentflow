CREATE TABLE IF NOT EXISTS orders_v2 (
    order_id VARCHAR PRIMARY KEY,
    user_id VARCHAR,
    status VARCHAR,
    total_amount DECIMAL(10,2),
    currency VARCHAR DEFAULT 'USD',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users_enriched (
    user_id VARCHAR PRIMARY KEY,
    total_orders INTEGER DEFAULT 0,
    total_spent DECIMAL(10,2) DEFAULT 0,
    first_order_at TIMESTAMP,
    last_order_at TIMESTAMP,
    preferred_category VARCHAR
);

CREATE TABLE IF NOT EXISTS debezium_signal (
    id VARCHAR PRIMARY KEY,
    type VARCHAR NOT NULL,
    data JSONB
);

INSERT INTO orders_v2
(order_id, user_id, status, total_amount, currency)
VALUES
('ORD-CDC-SEED-1', 'USR-CDC-SEED-1', 'confirmed', 42.50, 'USD')
ON CONFLICT (order_id) DO NOTHING;

INSERT INTO users_enriched
(user_id, total_orders, total_spent, first_order_at, last_order_at, preferred_category)
VALUES
('USR-CDC-SEED-1', 1, 42.50, NOW(), NOW(), 'electronics')
ON CONFLICT (user_id) DO NOTHING;
