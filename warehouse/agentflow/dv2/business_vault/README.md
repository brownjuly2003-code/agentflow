# AgentFlow DV2 Business Vault

Read-only `VIEW` layer over `raw_vault`. Owns conflict resolution between
sources and produces canonical per-branch entities for downstream marts.

## Objects

| Object | Layer | Branch | Joins |
| ------ | ----- | ------ | ----- |
| `bv_customer_mdm__msk.sql` | view | msk | `hub_customer` ⨝ `sat_customer_personal__1c__msk` (PII) ⨝ `sat_customer_loyalty__bitrix__msk` (loyalty) |
| `bv_customer_mdm__dxb.sql` | view | dxb | `hub_customer` ⨝ `sat_customer_personal__1c__dxb` (PII only — Bitrix loyalty not wired in DXB) |
| `bv_order_canonical.sql`   | view | all | `hub_order` ⨝ Bitrix header ⨝ 1C pricing ⨝ WB marketplace state ⨝ customer/store links |

## Conflict policy

- **PII** (name / email / phone): 1C wins — accounting source of truth.
- **Loyalty** (segment / points / last_visit): Bitrix wins — live CRM state.
- **Order header** (status / channel / total): Bitrix wins.
- **Order pricing** (subtotal / discount / tax / shipping): 1C wins.
- **Marketplace** (wb_status / commission / return_window): Wildberries
  satellite only — null when the order is not marketplace-sourced.

Each canonical row exposes `*_source` columns naming the satellite that
contributed each block, so downstream consumers can audit which source
won without re-reading raw_vault.

## SCD2 collapse

The views use `argMax(col, load_ts) GROUP BY entity_hk` to collapse
satellite history into the most recent effective row. Point-in-time
travel is intentionally **not** in these views — it belongs in a sibling
`bv_*_pit` object that takes an `as_of_ts` parameter.

## Why per-branch views for customer MDM, but a single view for orders

Customer PII is jurisdiction-bound — a row from `1c__dxb` must not be
visible to an MSK analyst without explicit policy. Keeping the MDM view
per-branch makes ClickHouse RBAC the enforcement primitive. The actual
policy set lives in `../governance/` (ADR 0006 Phase 2): column-limited
grants for `dv2_analyst` (no contact PII anywhere), per-jurisdiction
`dv2_pii_officer__<branch>` roles, and row policies scoping the shared
`hub_customer`. The MDM views run `SQL SECURITY DEFINER` so those
column grants work without exposing the underlying personal satellites.

Orders are jurisdictionally tagged in their own `branch` column, and
finance / mart layers need cross-branch P&L. A single `bv_order_canonical`
with `branch` as a regular column keeps that join cheap.

## Apply

```bash
for f in business_vault/*.sql; do
  cat "$f" | clickhouse-client --user default --password demo --multiquery
done
```

`infrastructure/dv2/bootstrap.sh` does not auto-apply this layer because it
is optional — add the loop manually after the raw vault is populated.
Apply `../governance/*.sql` (roles, grants, row policies) right after this
loop — see `../governance/README.md`.

## Current state in `hq-demo` (2026-05-23, after satellite seed)

Applied against the running cluster with
`warehouse/agentflow/dv2/satellite_seed.sql` populating the PII / loyalty /
header / pricing satellites:

| View | rows | rows_with_PII | rows_with_loyalty | rows_with_header / pricing |
| ---- | ---- | ------------- | ----------------- | -------------------------- |
| `bv_customer_mdm__msk` | 800   | 800 | 640 (160 pii_only) | — |
| `bv_customer_mdm__dxb` | 200   | 200 | n/a (no Bitrix in DXB) | — |
| `bv_order_canonical`   | 10000 | n/a | n/a | 4000 / 4000 for msk; 0 for spb/ekb/dxb/ala |

PII + loyalty merge example from `bv_customer_mdm__msk`:

```
Ivan   Volkov   cust236@example.test  gold     3068  pii=1c__msk  loy=bitrix__msk
Egor   Petrov   cust833@example.test  bronze  10829  pii=1c__msk  loy=bitrix__msk
Lena   Sidorov  cust138@example.test  bronze   1794  pii=1c__msk  loy=bitrix__msk
```

The 160 `pii_only` rows (msk customers without a Bitrix profile) keep
`loyalty_source = NULL` thanks to the LEFT JOIN — analysts see "no
loyalty yet" rather than the row silently dropping.

`bv_order_canonical` for the msk slice picks Bitrix header + 1C pricing
for every row; the other branches keep hub-level rows visible with NULL
header / pricing, waiting on their own satellite seed.
