# DV2 vault PII governance, PostgreSQL port — live verification (ADR 0006 Phase 2 follow-up)

**Date:** 2026-07-03
**Environment:** standalone PostgreSQL 17.5 (EDB windows-x64 binaries, no
Docker, no service install: `initdb` + `pg_ctl`, port 55432, trust auth,
user/db `agentflow`) — the same no-Docker standalone-PG recipe as
`vault-pii-governance-pg-verify-2026-07-02.md`, re-run on the current
kitchen-gadget legend. Vault built from the repo files verbatim via
`postgres/apply.sh` (schema → 8 hubs → 8 links → 48 satellites →
`03_business_vault.sql`), then `postgres/governance/01..04.sql`. Data: the
deterministic demo seed from `verify_live.sh` (`SEED_DEMO=1`): hub_customer
msk 8 / dxb 2 = 10 rows, the msk rows deliberately spanning three source
conventions — **`1c__msk`, `pg_ops__msk`, `mp__msk`** (the legacy
marketplace-seed prefix was retired in B2; this run confirms `mp__msk` is
what the seed now carries) —
so the row policies are exercised against the `split_part` branch derivation,
not a single record_source literal. Probe principals are stand-local:
`analyst_probe` (role `dv2_analyst`), `officer_msk_probe`, `officer_dxb_probe`,
and `noscope_probe` (SELECT on the hub, addressed by NO policy).

**Result: 33/33 probes passed** (`postgres/governance/verify_live.sh`,
transcript below; 0 FAIL, 0 WARN). The PII boundary is enforced by PostgreSQL
ACLs on resolved attributes — there is no SQL shape that reaches an ungranted
PII column, including the whole-row and positional-rename shapes that
ClickHouse cannot even express. The four governance files re-apply cleanly
(idempotency section, all four PASS).

## Transcript

```
$ PSQL="psql -h 127.0.0.1 -p 55432 -U agentflow -d agentflow" SEED_DEMO=1 bash verify_live.sh
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

- Verified on the stand-local demo seed (10 hub rows), not on promoted CDC
  volume — the row-policy assertions compare officer-visible counts against
  admin-side per-branch counts, so the script re-runs unchanged on a stand
  with real data (leave `SEED_DEMO` unset).
- The admin/owner (`agentflow`) sees everything: engine policies bind *roles*;
  production would split the admin identity from human users.
- The dbt marts and `bv_order_canonical_mat` exist only on the ClickHouse
  stand; there is nothing to govern for them here.
- `initdb` on the Windows temp filesystem is slow under Defender first-exec
  scanning (~7 min); `--no-sync` + `fsync=off` are safe on a throwaway stand.
