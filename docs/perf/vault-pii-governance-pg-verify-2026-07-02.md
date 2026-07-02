# DV2 vault PII governance, PostgreSQL port — live verification (ADR 0006 Phase 2 follow-up)

**Date:** 2026-07-02
**Environment:** standalone PostgreSQL 17.5 (EDB windows-x64 binaries, no
Docker, no service install: `initdb` + `pg_ctl` on port 55432) — the
PostgreSQL counterpart of the standalone-ClickHouse setup that verified the
ClickHouse governance layer (`vault-pii-governance-verify-2026-07-02.md`).
Vault built from the repo files verbatim via `postgres/apply.sh` (schema →
8 hubs → 8 links → 48 satellites → `03_business_vault.sql`), then
`postgres/governance/01..04.sql`. Data: the deterministic demo seed from
`verify_live.sh` (`SEED_DEMO=1`): hub_customer msk 8 / dxb 2 = 10 rows, msk
rows deliberately spanning three source conventions (`1c__msk`,
`pg_ops__msk`, `x5__msk`) so the row policies are exercised against the
split_part branch derivation, not a single record_source literal. Probe
principals are stand-local: `analyst_probe` (role `dv2_analyst`),
`officer_msk_probe`, `officer_dxb_probe`, and `noscope_probe` (SELECT on the
hub, addressed by NO policy — PostgreSQL-specific probe).

**Result: 33/33 probes passed** (`postgres/governance/verify_live.sh`,
transcript below). The PII boundary is enforced by PostgreSQL ACLs on
resolved attributes — there is no SQL shape that reaches an ungranted PII
column, including the shapes that ClickHouse could not even express.

## What the engine denies for `dv2_analyst` (column-limited)

| Probe | Result |
| ----- | ------ |
| `SELECT email FROM rv.bv_customer_mdm__msk` | `permission denied` |
| `SELECT *` | `permission denied` |
| Bypass #1: whole-row ref `SELECT t FROM ... AS t` | `permission denied` — expressible on PostgreSQL (unlike ClickHouse), checked on resolved attributes |
| Bypass #2: `to_jsonb(t)` whole-row serialization | `permission denied` |
| Bypass #3: positional rename-list `AS t(a,b,...)` | `permission denied` — expressible on PostgreSQL (unlike ClickHouse); renaming does not move the attribute ACL |
| PII inside expression `upper(email)` | `permission denied` |
| PII in WHERE only (`SELECT customer_bk ... WHERE email LIKE '%@%'`) | `permission denied` |
| PII via subquery (`SELECT count(*) FROM (SELECT email ...)`) | `permission denied` |
| Raw `sat_customer_personal__1c__msk` (no grant) | `permission denied` |
| `sat_employee_profile__1c_zup__msk` (employee names, no grant) | `permission denied` |

The two bypass forms that ClickHouse refuses to parse (`UNKNOWN_IDENTIFIER`)
are **valid SQL on PostgreSQL** — whole-row references and positional alias
rename-lists both resolve to real attributes, at which point the missing
column privilege denies them. Same conclusion as on ClickHouse, reached the
only way it can be reached on this engine: by not granting the column, not by
recognizing SQL shapes.

## What works for `dv2_analyst`

Explicit non-PII projections, bare `count(*)`, aggregates over granted
columns, `GROUP BY`/`HAVING`, `WHERE` on passthrough columns, granted
satellites, full hub visibility via the `jurisdiction__all` policy.

**The ClickHouse ergonomic limitation does not exist on PostgreSQL.**
Filtering on a view column derived through the SCD2 collapse
(`loyalty_segment` etc.) works directly for the column-limited role —
`SELECT count(*) FILTER (WHERE loyalty_segment = 'gold')` passes with no
subquery-wrap workaround. PostgreSQL checks privileges on the view's own
attributes; nothing is pushed past the view boundary for attribution.

## Row scoping and the PostgreSQL-specific semantics

| Probe | Result |
| ----- | ------ |
| `officer_msk` hub count | 8 of 8 msk rows (incl. `pg_ops__msk`, `x5__msk`) |
| `officer_dxb` hub count | 2 of 2 dxb rows |
| `officer_dxb` counts msk rows via hub filter | 0 |
| `officer_msk` cross-branch view / satellite | `permission denied` |
| `noscope_probe`: SELECT granted on hub, **no policy addresses it** | **0 rows** — PostgreSQL RLS is default-deny; there is no `users_without_row_policies_can_read_rows` analog to pin against, which is why `jurisdiction__all` addresses `dv2_analyst` explicitly (and must never be `TO PUBLIC`: permissive policies OR together and would void the officer scoping) |
| admin (owner) hub count / PII read | full 10 rows, PII readable — `ENABLE` (not `FORCE`) row level security: the owner bypasses RLS, which is also what keeps the owner-executed MDM views (PostgreSQL's DEFINER analog) returning rows |
| governance files re-applied | all 4 idempotent (DO-block roles, additive grants, DROP+CREATE policies) |

## Gotcha caught live

PostgreSQL **block comments nest**: a literal `satellites/*.sql` glob inside a
header comment opened a nested `/*`, and psql failed the whole file with
`unterminated /* comment`. Fixed by rewording the comment; pinned for all four
governance files by `test_dv2_postgres_governance_ddl.py`
(`test_no_nested_block_comments`).

## Transcript

```
$ PSQL="psql -h localhost -p 55432 -U agentflow -d agentflow" SEED_DEMO=1 bash verify_live.sh
=== setup: probe users (stand-local, not part of the governance files) ===
users ready
=== setup: deterministic demo seed (SEED_DEMO=1) ===
seed applied

=== dv2_analyst: non-PII access works (owner-rights views, column grants) ===
PASS  [analyst explicit non-PII projection] -> CUST-MSK-1|msk|gold CUST-MSK-2|msk|silver
PASS  [analyst bare count(*)] -> 8
PASS  [analyst aggregate over granted column] -> 8|1680.50
PASS  [analyst GROUP BY + HAVING on granted columns] -> |6 gold|1
PASS  [analyst WHERE on passthrough column (customer_bk)] -> CUST-MSK-1
PASS  [analyst filter on view-derived column (CH limitation absent on PG)] -> 1
PASS  [analyst hub_customer full visibility (jurisdiction__all policy)] -> 10
PASS  [analyst granted satellite (loyalty)] -> 2

=== dv2_analyst: PII columns are engine-denied in EVERY shape ===
PASS  [analyst plain PII column] -> permission denied
PASS  [analyst SELECT *] -> permission denied
PASS  [analyst bypass #1: whole-row ref] -> permission denied
PASS  [analyst bypass #2: to_jsonb(whole row)] -> permission denied
PASS  [analyst bypass #3: positional rename-list (expressible on PG)] -> permission denied
PASS  [analyst PII inside expression] -> permission denied
PASS  [analyst PII in WHERE only] -> permission denied
PASS  [analyst PII via subquery] -> permission denied
PASS  [analyst raw personal satellite] -> permission denied
PASS  [analyst employee profile (name PII)] -> permission denied

=== officers: PII bounded to own jurisdiction ===
PASS  [officer_msk reads own-branch PII] -> Ivan|ivan.petrov@example.com
PASS  [officer_msk filtered aggregate (full view grant)] -> 2
PASS  [officer_msk reads own personal satellite] -> 2
PASS  [officer_msk cross-branch view denied] -> permission denied
PASS  [officer_msk cross-branch satellite denied] -> permission denied
PASS  [officer_msk hub row-scoped] -> sees 8 of 8 msk rows
PASS  [officer_dxb hub row-scoped] -> sees 2 of 2 dxb rows
PASS  [officer_dxb sees zero msk rows via hub filter] -> 0

=== PostgreSQL default-deny: principal addressed by NO row policy ===
PASS  [noscope_probe (SELECT granted, no policy) sees zero hub rows] -> 0

=== admin (owner) unaffected: ENABLE (not FORCE) row level security ===
PASS  [admin hub full visibility (owner bypasses RLS)] -> 10
PASS  [admin reads PII] -> ivan.petrov@example.com

=== governance files re-apply cleanly (idempotency) ===
PASS  [re-apply 01_roles.sql]
PASS  [re-apply 02_grants_analyst.sql]
PASS  [re-apply 03_grants_pii_officers.sql]
PASS  [re-apply 04_row_policies.sql]
```

## Honest scope

- Verified on a stand-local demo seed (10 hub rows), not on promoted CDC
  volume — the row-policy assertions in `verify_live.sh` compare
  officer-visible counts against admin-side per-branch counts, so the script
  re-runs unchanged on a stand with real data (leave `SEED_DEMO` unset).
- The admin/owner (`agentflow`) sees everything: engine policies bound
  *roles*; production would split the admin identity from human users (same
  note as the ClickHouse layer).
- The dbt marts and `bv_order_canonical_mat` exist only on the ClickHouse
  stand; there is nothing to govern for them here.
