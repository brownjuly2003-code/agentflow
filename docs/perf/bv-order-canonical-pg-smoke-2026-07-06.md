# `bv_order_canonical` live smoke — PostgreSQL (G1 Mac stand)

**Date:** 2026-07-06
**Environment:** `postgres:16` container (PostgreSQL 16.14, Debian) on the iMac
demo host under Colima/Docker. The repo is bind-mounted read-only at `/repo`;
the vault and smoke seed are applied and queried entirely inside the container
(`docker exec`), so no host `psql` and no published port are involved. The
DV2 raw vault is built from the repo files verbatim via `postgres/apply.sh`
(`00_schema.sql` → `01_hubs.sql` → `02_links.sql` → all 48 satellites →
`03_business_vault.sql`), then the idempotent order seed
(`smoke/order_smoke_seed.sql`) lands the eight hand-verifiable orders.

This is the live counterpart to the by-hand expected table in
`warehouse/agentflow/dv2/postgres/smoke/README.md`, run with `APPLY=1` so the
vault is built fresh in the same invocation. It complements the customer-side
`postgres/governance/verify_live.sh` transcript
([`vault-pii-governance-pg-verify-2026-07-03.md`](vault-pii-governance-pg-verify-2026-07-03.md)):
governance exercises `bv_customer_mdm__<branch>`, this exercises the
reconstruction-heavy `bv_order_canonical` (per-source SCD2 collapse over a
`UNION ALL`, LEFT JOINs of header + pricing + marketplace + customer + store).

**Result: 17/17 assertions PASS** (0 FAIL, exit 0). Every invariant pinned by
hand in `smoke/README.md` reproduces against a real running PostgreSQL: the
eight-order shape and branch derivation, the RUB total (`197166.67`, net of
VAT), the SCD2 latest-wins collapse across the cross-source `UNION`, the
soft-delete tombstone that must not win, the `bitrix__<branch>` header
attribution, the `ala` pricing LEFT-JOIN miss, marketplace state lighting up
for msk only, and per-jurisdiction VAT (UAE 5 % / RU 20 %) surfacing through
the 1C pricing satellites.

## How it was run

```bash
docker run -d --name g2s6-pg \
  -e POSTGRES_USER=agentflow -e POSTGRES_PASSWORD=agentflow \
  -e POSTGRES_DB=agentflow -e POSTGRES_HOST_AUTH_METHOD=trust \
  -v ~/agentflow-docker-check:/repo:ro postgres:16
# once pg_isready:
docker exec g2s6-pg bash -c 'cd /repo/warehouse/agentflow/dv2/postgres && \
  PSQL="psql -U agentflow -d agentflow" APPLY=1 bash smoke/verify_bv_order.sh'
```

## Transcript

```
=== setup: apply.sh (fresh vault) ===
vault applied
=== setup: order smoke seed (idempotent) ===
seed applied

=== reconstruction: shape and coverage ===
PASS  [row count = 8 canonical orders] -> 8
PASS  [branch derivation via split_part (msk 4 + 4 regionals)] -> ala:1 dxb:1 ekb:1 msk:4 spb:1
PASS  [no branch escapes the five jurisdictions] -> 0
PASS  [customer + store links all resolved] -> 8
PASS  [total_amount sum (RUB, net of VAT)] -> 197166.67

=== SCD2: latest load_ts wins ===
PASS  [O2 header collapses across UNION to newest Bitrix version] -> shipped|2166.67
PASS  [O2 pricing collapses to newest 1C version] -> 2166.67|433.33
PASS  [O2 marketplace collapses to newest wb version] -> delivering
PASS  [O4 soft-delete tombstone (newer is_deleted=1) does NOT win] -> confirmed

=== conflict policy: source attribution ===
PASS  [every order's header_source = bitrix__<branch>] -> 8
PASS  [pricing present for 7 of 8 (O8 ala has none)] -> 7
PASS  [O8 pricing LEFT JOIN miss -> NULL pricing] -> NULL|NULL

=== marketplace: Wildberries lights up for MSK only ===
PASS  [O1 marketplace joined (wb__msk)] -> delivered|wb__msk
PASS  [only the 2 msk marketplace orders carry marketplace state] -> 2
PASS  [O3 D2C has no marketplace state] -> NULL

=== per-jurisdiction VAT surfaces through pricing ===
PASS  [dxb effective VAT rate = 5% (UAE)] -> 5
PASS  [spb effective VAT rate = 20% (RU)] -> 20

Done. pass=17 fail=0
```

## Honest scope

- PostgreSQL **16.14** (the image cached on this Mac), not the 17.5 EDB build
  used for the 2026-07-03 standalone governance transcript. The vault DDL is
  standard SQL (schemas, `DISTINCT ON`, `split_part`, LEFT JOINs) and version-
  independent across PG 12+; the smoke exercises view logic, not any 17-only
  feature. Run inside a container because that is the tooling available on the
  shared Mac stand — the script itself is Docker-agnostic (`PSQL` is any psql
  invocation).
- This is the **standalone seed smoke** of the view logic (eight deterministic
  orders), not a run against promoted CDC volume. The end-to-end
  CDC → serving variant remains the true Mac-tail; the `bv_order_canonical`
  SQL exercised is identical either way. See `smoke/README.md` "Honest scope".
