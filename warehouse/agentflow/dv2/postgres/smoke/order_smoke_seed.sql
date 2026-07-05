-- =====================================================================
-- bv_order_canonical smoke seed — PostgreSQL dialect (G1 Mac smoke).
-- =====================================================================
-- Own-brand kitchen-appliance importer legend (docs/domain.md,
-- docs/generator-spec.md). RUB amounts, per-jurisdiction VAT (RU 20 % /
-- UAE 5 % / KZ 12 %), five branches (msk / spb / ekb / dxb / ala).
--
-- Purpose: give rv.bv_order_canonical a small, hand-verifiable order set so a
-- live query proves the business-vault reconstruction end-to-end — the
-- sub-step the governance verify (which seeds only the CUSTOMER side, see
-- governance/verify_live.sh SEED_DEMO) never exercised. Expected output is
-- pinned in smoke/README.md and asserted by smoke/verify_bv_order.sh.
--
-- Conventions mirror the ClickHouse synthetic_seed.sql exactly, ported to the
-- PostgreSQL idiom used by governance/verify_live.sh:
--   order_hk    = decode(md5(order_bk), 'hex')            -- BYTEA hash key
--   customer_hk = decode(md5(customer_bk), 'hex')
--   store_hk    = decode(md5(store_code), 'hex')
--   link_hk     = decode(md5(order_bk || '|' || <member_bk>), 'hex')
--   branch      = split_part(hub_order.record_source, '__', 2)
-- All inserts are idempotent (ON CONFLICT DO NOTHING), so the seed is
-- repeatable and safe to re-run on a stand that already carries it.
--
-- Numbering follows synthetic_seed.sql order bands (§11): mp__msk marketplace,
-- site__msk D2C, bitrix__<branch> B2B. Order business keys are
-- <record_source>__<7-digit>, e.g. mp__msk__0000001.
--
-- Coverage (one canonical row per hub_order, 8 orders total):
--   O1 mp__msk__0000001    msk marketplace — all three sources present, wb lit
--   O2 mp__msk__0000002    msk marketplace — SCD2 latest-wins across the header
--                          UNION (bitrix beats an older 1c header) + per-sat
--                          collapse of pricing and marketplace
--   O3 site__msk__0008901  msk D2C — no marketplace row (marketplace_source NULL)
--   O4 bitrix__msk__0009181 msk B2B — soft-delete tombstone: a newer is_deleted=1
--                          header must NOT win over the older active version
--   O5 bitrix__spb__0009541 spb B2B — branch derivation + RU 20 % VAT
--   O6 bitrix__ekb__0009721 ekb B2B — branch derivation
--   O7 bitrix__dxb__0009851 dxb B2B — UAE 5 % VAT
--   O8 bitrix__ala__0009925 ala B2B — KZ jurisdiction, cancelled, and NO pricing
--                          row (pricing LEFT JOIN miss -> pricing_source NULL)
--
-- NOTE on O2's 1C header: the production seed writes order headers only to the
-- Bitrix satellites (satellite_seed.sql — "Bitrix wins" for the header). O2
-- carries a single, deliberately older 1c__msk header purely to exercise the
-- header UNION+DISTINCT ON collapse across sources; it is a smoke fixture, not
-- a claim about the production loader.

-- ============ HUBS ============
INSERT INTO rv.hub_store (store_hk, store_bk, record_source) VALUES
 (decode(md5('msk-01'),'hex'),'msk-01','1c__global'),
 (decode(md5('spb-01'),'hex'),'spb-01','1c__global'),
 (decode(md5('ekb-01'),'hex'),'ekb-01','1c__global'),
 (decode(md5('dxb-01'),'hex'),'dxb-01','1c__global'),
 (decode(md5('ala-01'),'hex'),'ala-01','1c__global')
ON CONFLICT (store_hk) DO NOTHING;

INSERT INTO rv.hub_customer (customer_hk, customer_bk, record_source) VALUES
 (decode(md5('CUST-R-01'),'hex'),'CUST-R-01','1c__msk'),
 (decode(md5('CUST-R-02'),'hex'),'CUST-R-02','mp__msk'),
 (decode(md5('CUST-D-MSK'),'hex'),'CUST-D-MSK','1c__msk'),
 (decode(md5('CUST-D-SPB'),'hex'),'CUST-D-SPB','1c__spb'),
 (decode(md5('CUST-D-EKB'),'hex'),'CUST-D-EKB','1c__ekb'),
 (decode(md5('CUST-D-DXB'),'hex'),'CUST-D-DXB','1c__dxb'),
 (decode(md5('CUST-D-ALA'),'hex'),'CUST-D-ALA','1c__ala')
ON CONFLICT (customer_hk) DO NOTHING;

INSERT INTO rv.hub_order (order_hk, order_bk, record_source) VALUES
 (decode(md5('mp__msk__0000001'),'hex'),'mp__msk__0000001','mp__msk'),
 (decode(md5('mp__msk__0000002'),'hex'),'mp__msk__0000002','mp__msk'),
 (decode(md5('site__msk__0008901'),'hex'),'site__msk__0008901','site__msk'),
 (decode(md5('bitrix__msk__0009181'),'hex'),'bitrix__msk__0009181','bitrix__msk'),
 (decode(md5('bitrix__spb__0009541'),'hex'),'bitrix__spb__0009541','bitrix__spb'),
 (decode(md5('bitrix__ekb__0009721'),'hex'),'bitrix__ekb__0009721','bitrix__ekb'),
 (decode(md5('bitrix__dxb__0009851'),'hex'),'bitrix__dxb__0009851','bitrix__dxb'),
 (decode(md5('bitrix__ala__0009925'),'hex'),'bitrix__ala__0009925','bitrix__ala')
ON CONFLICT (order_hk) DO NOTHING;

-- ============ LINKS ============
-- lnk_order_customer: marketplace/D2C draw from retail; B2B from own-branch dealer.
INSERT INTO rv.lnk_order_customer (link_hk, order_hk, customer_hk, record_source) VALUES
 (decode(md5('mp__msk__0000001|CUST-R-02'),'hex'),   decode(md5('mp__msk__0000001'),'hex'),   decode(md5('CUST-R-02'),'hex'),  'mp__msk'),
 (decode(md5('mp__msk__0000002|CUST-R-01'),'hex'),   decode(md5('mp__msk__0000002'),'hex'),   decode(md5('CUST-R-01'),'hex'),  'mp__msk'),
 (decode(md5('site__msk__0008901|CUST-R-01'),'hex'), decode(md5('site__msk__0008901'),'hex'), decode(md5('CUST-R-01'),'hex'),  'site__msk'),
 (decode(md5('bitrix__msk__0009181|CUST-D-MSK'),'hex'), decode(md5('bitrix__msk__0009181'),'hex'), decode(md5('CUST-D-MSK'),'hex'), 'bitrix__msk'),
 (decode(md5('bitrix__spb__0009541|CUST-D-SPB'),'hex'), decode(md5('bitrix__spb__0009541'),'hex'), decode(md5('CUST-D-SPB'),'hex'), 'bitrix__spb'),
 (decode(md5('bitrix__ekb__0009721|CUST-D-EKB'),'hex'), decode(md5('bitrix__ekb__0009721'),'hex'), decode(md5('CUST-D-EKB'),'hex'), 'bitrix__ekb'),
 (decode(md5('bitrix__dxb__0009851|CUST-D-DXB'),'hex'), decode(md5('bitrix__dxb__0009851'),'hex'), decode(md5('CUST-D-DXB'),'hex'), 'bitrix__dxb'),
 (decode(md5('bitrix__ala__0009925|CUST-D-ALA'),'hex'), decode(md5('bitrix__ala__0009925'),'hex'), decode(md5('CUST-D-ALA'),'hex'), 'bitrix__ala')
ON CONFLICT (link_hk) DO NOTHING;

-- lnk_order_store: msk central warehouse fulfils mp/D2C/its own B2B; regionals fulfil own B2B.
INSERT INTO rv.lnk_order_store (link_hk, order_hk, store_hk, record_source) VALUES
 (decode(md5('mp__msk__0000001|msk-01'),'hex'),   decode(md5('mp__msk__0000001'),'hex'),   decode(md5('msk-01'),'hex'), '1c__global'),
 (decode(md5('mp__msk__0000002|msk-01'),'hex'),   decode(md5('mp__msk__0000002'),'hex'),   decode(md5('msk-01'),'hex'), '1c__global'),
 (decode(md5('site__msk__0008901|msk-01'),'hex'), decode(md5('site__msk__0008901'),'hex'), decode(md5('msk-01'),'hex'), '1c__global'),
 (decode(md5('bitrix__msk__0009181|msk-01'),'hex'), decode(md5('bitrix__msk__0009181'),'hex'), decode(md5('msk-01'),'hex'), '1c__global'),
 (decode(md5('bitrix__spb__0009541|spb-01'),'hex'), decode(md5('bitrix__spb__0009541'),'hex'), decode(md5('spb-01'),'hex'), '1c__global'),
 (decode(md5('bitrix__ekb__0009721|ekb-01'),'hex'), decode(md5('bitrix__ekb__0009721'),'hex'), decode(md5('ekb-01'),'hex'), '1c__global'),
 (decode(md5('bitrix__dxb__0009851|dxb-01'),'hex'), decode(md5('bitrix__dxb__0009851'),'hex'), decode(md5('dxb-01'),'hex'), '1c__global'),
 (decode(md5('bitrix__ala__0009925|ala-01'),'hex'), decode(md5('bitrix__ala__0009925'),'hex'), decode(md5('ala-01'),'hex'), '1c__global')
ON CONFLICT (link_hk) DO NOTHING;

-- ============ ORDER HEADER (Bitrix — production source of truth) ============
-- hash_diff distinguishes SCD2 versions (msk O2 v1/v2, O4 v1/v2).
INSERT INTO rv.sat_order_header__bitrix__msk
    (order_hk, load_ts, hash_diff, order_date, channel, order_status, total_amount, is_deleted) VALUES
 -- O1: single delivered marketplace header. total_amount = subtotal (net of
 -- VAT), mirroring satellite_seed.sql — tax lives only in the pricing sat.
 (decode(md5('mp__msk__0000001'),'hex'),   '2026-07-01 09:00:00', decode(md5('mp__msk__0000001|hdr|v1'),'hex'),   '2026-06-28 14:12:00', 'marketplace', 'delivered', 2000.00, 0),
 -- O2: two versions — pending@09:00 then shipped@12:00 (latest wins). Net
 -- totals track each version's pricing subtotal (2100 -> 2166.67).
 (decode(md5('mp__msk__0000002'),'hex'),   '2026-07-01 09:00:00', decode(md5('mp__msk__0000002|hdr|v1'),'hex'),   '2026-06-29 10:05:00', 'marketplace', 'pending',   2100.00, 0),
 (decode(md5('mp__msk__0000002'),'hex'),   '2026-07-01 12:00:00', decode(md5('mp__msk__0000002|hdr|v2'),'hex'),   '2026-06-29 10:05:00', 'marketplace', 'shipped',   2166.67, 0),
 -- O3: D2C delivered
 (decode(md5('site__msk__0008901'),'hex'), '2026-07-01 10:00:00', decode(md5('site__msk__0008901|hdr|v1'),'hex'), '2026-06-30 18:40:00', 'd2c',         'delivered', 3000.00, 0),
 -- O4: active confirmed@10:00, then a soft-delete tombstone@14:00 (is_deleted=1, must NOT win)
 (decode(md5('bitrix__msk__0009181'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__msk__0009181|hdr|v1'),'hex'), '2026-06-27 09:15:00', 'b2b', 'confirmed', 50000.00, 0),
 (decode(md5('bitrix__msk__0009181'),'hex'), '2026-07-01 14:00:00', decode(md5('bitrix__msk__0009181|hdr|v2'),'hex'), '2026-06-27 09:15:00', 'b2b', 'cancelled', 50000.00, 1)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

INSERT INTO rv.sat_order_header__bitrix__spb
    (order_hk, load_ts, hash_diff, order_date, channel, order_status, total_amount, is_deleted) VALUES
 (decode(md5('bitrix__spb__0009541'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__spb__0009541|hdr|v1'),'hex'), '2026-06-26 11:00:00', 'b2b', 'delivered', 40000.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

INSERT INTO rv.sat_order_header__bitrix__ekb
    (order_hk, load_ts, hash_diff, order_date, channel, order_status, total_amount, is_deleted) VALUES
 (decode(md5('bitrix__ekb__0009721'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__ekb__0009721|hdr|v1'),'hex'), '2026-06-25 16:30:00', 'b2b', 'delivered', 30000.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

INSERT INTO rv.sat_order_header__bitrix__dxb
    (order_hk, load_ts, hash_diff, order_date, channel, order_status, total_amount, is_deleted) VALUES
 (decode(md5('bitrix__dxb__0009851'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__dxb__0009851|hdr|v1'),'hex'), '2026-06-24 08:20:00', 'b2b', 'delivered', 40000.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

INSERT INTO rv.sat_order_header__bitrix__ala
    (order_hk, load_ts, hash_diff, order_date, channel, order_status, total_amount, is_deleted) VALUES
 (decode(md5('bitrix__ala__0009925'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__ala__0009925|hdr|v1'),'hex'), '2026-06-23 12:00:00', 'b2b', 'cancelled', 30000.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

-- O2 only: an OLDER 1C header (08:00) to exercise the header UNION+DISTINCT ON
-- collapse across sources — the newer Bitrix shipped@12:00 row must still win.
INSERT INTO rv.sat_order_header__1c__msk
    (order_hk, load_ts, hash_diff, order_date, channel, order_status, total_amount, is_deleted) VALUES
 (decode(md5('mp__msk__0000002'),'hex'), '2026-07-01 08:00:00', decode(md5('mp__msk__0000002|hdr|1c'),'hex'), '2026-06-29 10:05:00', 'marketplace', 'pending', 2050.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

-- ============ ORDER PRICING (1C — RUB, per-jurisdiction VAT) ============
-- O8 (ala) intentionally has NO pricing row -> pricing LEFT JOIN miss.
INSERT INTO rv.sat_order_pricing__1c__msk
    (order_hk, load_ts, hash_diff, subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted) VALUES
 -- O1: RU 20 % VAT
 (decode(md5('mp__msk__0000001'),'hex'),   '2026-07-01 09:00:00', decode(md5('mp__msk__0000001|prc|v1'),'hex'),   2000.00, 0.00,   400.00,  199.00, 0),
 -- O2: two pricing versions — latest (12:00) wins
 (decode(md5('mp__msk__0000002'),'hex'),   '2026-07-01 09:00:00', decode(md5('mp__msk__0000002|prc|v1'),'hex'),   2100.00, 0.00,   420.00,  199.00, 0),
 (decode(md5('mp__msk__0000002'),'hex'),   '2026-07-01 12:00:00', decode(md5('mp__msk__0000002|prc|v2'),'hex'),   2166.67, 0.00,   433.33,  199.00, 0),
 -- O3: D2C
 (decode(md5('site__msk__0008901'),'hex'), '2026-07-01 10:00:00', decode(md5('site__msk__0008901|prc|v1'),'hex'), 3000.00, 60.00,  600.00,  299.00, 0),
 -- O4: B2B msk
 (decode(md5('bitrix__msk__0009181'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__msk__0009181|prc|v1'),'hex'), 50000.00, 0.00, 10000.00, 500.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

INSERT INTO rv.sat_order_pricing__1c__spb
    (order_hk, load_ts, hash_diff, subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted) VALUES
 (decode(md5('bitrix__spb__0009541'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__spb__0009541|prc|v1'),'hex'), 40000.00, 0.00, 8000.00, 800.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

INSERT INTO rv.sat_order_pricing__1c__ekb
    (order_hk, load_ts, hash_diff, subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted) VALUES
 (decode(md5('bitrix__ekb__0009721'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__ekb__0009721|prc|v1'),'hex'), 30000.00, 0.00, 6000.00, 500.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

-- O7 dxb: UAE VAT 5 % (2000 on 40000).
INSERT INTO rv.sat_order_pricing__1c__dxb
    (order_hk, load_ts, hash_diff, subtotal_amount, discount_amount, tax_amount, shipping_cost, is_deleted) VALUES
 (decode(md5('bitrix__dxb__0009851'),'hex'), '2026-07-01 10:00:00', decode(md5('bitrix__dxb__0009851|prc|v1'),'hex'), 40000.00, 0.00, 2000.00, 500.00, 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;

-- ============ MARKETPLACE (Wildberries — MSK integration only) ============
-- Only the two msk marketplace orders carry a wb row; O2 carries two versions.
INSERT INTO rv.sat_order_marketplace__wb__msk
    (order_hk, load_ts, hash_diff, wb_status, wb_commission, return_window_until, is_deleted) VALUES
 (decode(md5('mp__msk__0000001'),'hex'), '2026-07-01 09:00:00', decode(md5('mp__msk__0000001|wb|v1'),'hex'), 'delivered',  240.00, '2026-07-31', 0),
 (decode(md5('mp__msk__0000002'),'hex'), '2026-07-01 09:00:00', decode(md5('mp__msk__0000002|wb|v1'),'hex'), 'sold',       260.00, '2026-08-01', 0),
 (decode(md5('mp__msk__0000002'),'hex'), '2026-07-01 12:00:00', decode(md5('mp__msk__0000002|wb|v2'),'hex'), 'delivering', 260.00, '2026-08-01', 0)
ON CONFLICT (order_hk, load_ts) DO NOTHING;
