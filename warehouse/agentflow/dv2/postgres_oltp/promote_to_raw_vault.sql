-- Hot -> warm promotion. Reads from the oltp_live bridge tables (which
-- live-read Postgres ops_<branch>) and lands hub + link + satellite rows
-- in rv.* exactly the way a real CDC consumer would.
--
-- Idempotent: hash_diff keeps satellites duplicate-free under
-- ReplacingMergeTree-friendly ORDER BY, hubs / links use
-- ReplacingMergeTree(load_ts).

-- ============ HUB CUSTOMER + LINK (MSK) ============
INSERT INTO rv.hub_customer (customer_hk, customer_bk, load_ts, record_source)
SELECT MD5(customer_id), customer_id, now64(3), 'pg_ops__msk'
FROM oltp_live.msk_customers;

INSERT INTO rv.sat_customer_personal__1c__msk
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    MD5(customer_id),
    now64(3),
    MD5(concat(customer_id, '|pg-oltp|v1')),
    'pg_ops__msk',
    first_name,
    last_name,
    coalesce(email, ''),
    coalesce(phone, ''),
    NULL,
    true,
    0
FROM oltp_live.msk_customers;

-- ============ HUB ORDER + SATELLITES (MSK) ============
INSERT INTO rv.hub_order (order_hk, order_bk, load_ts, record_source)
SELECT MD5(order_id), order_id, now64(3), 'pg_ops__msk'
FROM oltp_live.msk_orders;

INSERT INTO rv.sat_order_header__bitrix__msk
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(order_id),
    now64(3),
    MD5(concat(order_id, '|pg-hdr|v1')),
    'pg_ops__msk',
    order_date,
    channel,
    order_status,
    total_amount,
    0
FROM oltp_live.msk_orders;

INSERT INTO rv.lnk_order_customer (link_hk, order_hk, customer_hk, load_ts, record_source)
SELECT
    MD5(concat(order_id, '|', customer_id)),
    MD5(order_id),
    MD5(customer_id),
    now64(3),
    'pg_ops__msk'
FROM oltp_live.msk_orders;

-- ============ HUB CUSTOMER + LINK (DXB) ============
INSERT INTO rv.hub_customer (customer_hk, customer_bk, load_ts, record_source)
SELECT MD5(customer_id), customer_id, now64(3), 'pg_ops__dxb'
FROM oltp_live.dxb_customers;

INSERT INTO rv.sat_customer_personal__1c__dxb
    (customer_hk, load_ts, hash_diff, record_source,
     first_name, last_name, email, phone, birth_date, pii_flag, is_deleted)
SELECT
    MD5(customer_id),
    now64(3),
    MD5(concat(customer_id, '|pg-oltp|v1')),
    'pg_ops__dxb',
    first_name,
    last_name,
    coalesce(email, ''),
    coalesce(phone, ''),
    NULL,
    true,
    0
FROM oltp_live.dxb_customers;

INSERT INTO rv.hub_order (order_hk, order_bk, load_ts, record_source)
SELECT MD5(order_id), order_id, now64(3), 'pg_ops__dxb'
FROM oltp_live.dxb_orders;

INSERT INTO rv.sat_order_header__bitrix__dxb
    (order_hk, load_ts, hash_diff, record_source,
     order_date, channel, order_status, total_amount, is_deleted)
SELECT
    MD5(order_id),
    now64(3),
    MD5(concat(order_id, '|pg-hdr|v1')),
    'pg_ops__dxb',
    order_date,
    channel,
    order_status,
    total_amount,
    0
FROM oltp_live.dxb_orders;

INSERT INTO rv.lnk_order_customer (link_hk, order_hk, customer_hk, load_ts, record_source)
SELECT
    MD5(concat(order_id, '|', customer_id)),
    MD5(order_id),
    MD5(customer_id),
    now64(3),
    'pg_ops__dxb'
FROM oltp_live.dxb_orders;
