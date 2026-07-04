# `bv_order_canonical` live smoke (G1)

A small, hand-verifiable order set for the DV2 raw vault on PostgreSQL, plus a
script that queries `rv.bv_order_canonical` and asserts the reconstruction. This
is the order-side counterpart to `../governance/verify_live.sh`, which seeds and
exercises only the **customer** side (`bv_customer_mdm__<branch>`). Together they
cover both business-vault surfaces on a live PostgreSQL stand with no Docker.

## Why this exists

`bv_order_canonical` is the reconstruction-heavy view that motivates running the
vault on PostgreSQL (see `../README.md`): it collapses each satellite to its
latest version (`DISTINCT ON (order_hk) … ORDER BY load_ts DESC`) over a
`UNION ALL` of per-branch header and pricing satellites, then `LEFT JOIN`s
header + pricing + marketplace + customer + store. The governance verify never
touched it, so a live query against real order rows was the last unproven vault
sub-step (`../README.md`, "Apply and verify"). This seed makes that query
possible and deterministic.

## Run (Mac / any running PostgreSQL, no Docker)

```bash
# from warehouse/agentflow/dv2/postgres
PSQL="psql -h localhost -p 5432 -U agentflow -d agentflow" APPLY=1 \
  bash smoke/verify_bv_order.sh
```

`APPLY=1` runs `apply.sh` first (schema → hubs → links → 48 satellites →
`03_business_vault.sql`). Drop it if the vault is already applied. The seed
(`order_smoke_seed.sql`) is idempotent (`ON CONFLICT DO NOTHING`), so the script
is safe to re-run. Every printed line should start with `PASS`; the script exits
non-zero if any assertion fails.

The standalone no-Docker recipe used for the governance verifies
(`initdb` + `pg_ctl`, port 55432, trust auth) applies here unchanged — see
`docs/perf/vault-pii-governance-pg-verify-2026-07-03.md`.

## Expected canonical output (derived by hand from `order_smoke_seed.sql`)

Eight orders, one canonical row each. RUB amounts; VAT is RU 20 % / UAE 5 %.
`total_amount` is **net of VAT** — it mirrors the pricing subtotal (the
production `satellite_seed.sql` convention: "subtotal mirrors header.total_amount
(pre-tax)"); tax is a separate column, never folded into the total.

| order_bk | branch | channel | status | total | subtotal | tax | ship | wb_status | header_src | pricing_src | mkt_src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| mp__msk__0000001 | msk | marketplace | delivered | 2000.00 | 2000.00 | 400.00 | 199.00 | delivered | bitrix__msk | 1c__msk | wb__msk |
| mp__msk__0000002 | msk | marketplace | **shipped** | **2166.67** | **2166.67** | **433.33** | 199.00 | **delivering** | bitrix__msk | 1c__msk | wb__msk |
| site__msk__0008901 | msk | d2c | delivered | 3000.00 | 3000.00 | 600.00 | 299.00 | — | bitrix__msk | 1c__msk | — |
| bitrix__msk__0009181 | msk | b2b | **confirmed** | 50000.00 | 50000.00 | 10000.00 | 500.00 | — | bitrix__msk | 1c__msk | — |
| bitrix__spb__0009541 | spb | b2b | delivered | 40000.00 | 40000.00 | 8000.00 | 800.00 | — | bitrix__spb | 1c__spb | — |
| bitrix__ekb__0009721 | ekb | b2b | delivered | 30000.00 | 30000.00 | 6000.00 | 500.00 | — | bitrix__ekb | 1c__ekb | — |
| bitrix__dxb__0009851 | dxb | b2b | delivered | 40000.00 | 40000.00 | **2000.00** | 500.00 | — | bitrix__dxb | 1c__dxb | — |
| bitrix__ala__0009925 | ala | b2b | cancelled | 30000.00 | **—** | **—** | **—** | — | bitrix__ala | **—** | — |

Bold cells are the invariants the smoke targets:

- **SCD2 latest-wins** — `mp__msk__0000002` carries two Bitrix header versions
  (pending @09:00, shipped @12:00) *and* an older 1C header (@08:00); the view
  must return `shipped` (newest across the whole `UNION`). Pricing and
  marketplace collapse the same way (`2166.67`/`433.33`, `delivering`).
- **Soft-delete tombstone** — `bitrix__msk__0009181` has an active `confirmed`
  @10:00 and a newer `is_deleted=1` `cancelled` @14:00. The `WHERE is_deleted=0`
  filter drops the tombstone *before* the collapse, so `confirmed` wins — a
  soft-deleted latest version must never surface.
- **Marketplace = MSK only** — Wildberries state lights up for the two msk
  marketplace orders and is `NULL` everywhere else (`marketplace_source`
  non-null count = 2). The production seed never populated
  `sat_order_marketplace__wb__msk` at all, so this is new coverage.
- **Pricing LEFT JOIN miss** — `bitrix__ala__0009925` has a header but no 1C
  pricing row, so `pricing_source` and every pricing amount are `NULL`.
- **Per-jurisdiction VAT** — dxb effective rate `tax/subtotal = 5 %` (UAE), the
  RU branches `20 %`.
- **Branch derivation** — `split_part(record_source,'__',2)` yields
  msk×4 / spb / ekb / dxb / ala; `total_amount` (net of VAT) sums to
  `197166.67`.

## Honest scope

- This is a **standalone seed smoke** of the view logic, not a run against
  **promoted CDC volume**. On the Mac the same query also runs at the end of the
  full CDC → Kafka → serving path; that end-to-end variant remains the true
  Mac-tail. The view SQL exercised is identical either way.
- The seed writes headers to the Bitrix satellites and pricing to the 1C
  satellites, matching the production `satellite_seed.sql` attribution
  ("Bitrix wins" for the header). The single 1C header on
  `mp__msk__0000002` is a deliberate fixture to exercise the cross-source
  `UNION` collapse — it is not something the production loader emits.
- No-Docker CI gate: `order_smoke_seed.sql` is parsed under sqlglot's
  PostgreSQL dialect and checked for stray ClickHouse constructs by
  `tests/unit/test_dv2_postgres_ddl.py`, the same gate as the rest of the
  PostgreSQL vault.
