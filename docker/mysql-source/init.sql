GRANT SELECT, RELOAD, SHOW DATABASES, REPLICATION SLAVE, REPLICATION CLIENT
ON *.* TO 'cdc_reader'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS products_current (
    product_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255),
    category VARCHAR(128),
    price DECIMAL(10,2),
    in_stock BOOLEAN DEFAULT TRUE,
    stock_quantity INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions_aggregated (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64),
    started_at DATETIME,
    ended_at DATETIME NULL,
    duration_seconds FLOAT,
    event_count INT,
    unique_pages INT,
    funnel_stage VARCHAR(64),
    is_conversion BOOLEAN DEFAULT FALSE
);

INSERT IGNORE INTO products_current
(product_id, name, category, price, in_stock, stock_quantity)
VALUES
('PROD-CDC-SEED-1', 'CDC Widget', 'test', 9.99, TRUE, 10);

INSERT IGNORE INTO sessions_aggregated
(session_id, user_id, started_at, ended_at, duration_seconds, event_count, unique_pages, funnel_stage, is_conversion)
VALUES
('SES-CDC-SEED-1', 'USR-CDC-SEED-1', NOW(), NULL, NULL, 1, 1, 'browse', FALSE);
