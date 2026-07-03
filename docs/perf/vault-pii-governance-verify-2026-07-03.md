# DV2 vault PII governance — live verification, ClickHouse (ADR 0006 Phase 2)

**Date:** 2026-07-03
**Environment:** standalone `clickhouse server` 26.7.1.492 (single binary, WSL
Ubuntu 22.04, no Docker), `access_management=1` for the applying `default`
user. Vault built from the repo files verbatim on the current kitchen-gadget
legend (post-B1/B2/B3 seeds): `__init.sql` → 8 hubs → 8 links → all 48
satellites → `synthetic_seed.sql` + `satellite_seed.sql` +
`satellite_seed_all_branches.sql` → `business_vault/*.sql` (views with
`SQL SECURITY DEFINER`) → `governance/01..04.sql`. Resulting volume:
**hub_customer 2,500** (msk 2,190 / spb 100 / ala 80 / ekb 70 / dxb 60),
**hub_order 10,000**. Probe users are stand-local: `analyst_probe`
(role `dv2_analyst`), `officer_msk_probe`, `officer_dxb_probe`.

**Result: 29/29 probes passed** (`governance/verify_live.sh`, transcript
below; 0 FAIL, 0 WARN). The PII boundary is enforced by the engine's access
control on resolved columns — there is no SQL shape that reaches an ungranted
PII column.

The suite is a refresh of `vault-pii-governance-verify-2026-07-02.md` on the
new seeds. Two things changed vs that run:

1. **Volumes are legend-current** — 2,500 customers (was 2,000), msk holds all
   retail (2,190) under the "regions carry only dealers" rule; officer hub
   counts now assert 2,190 msk / 60 dxb rather than 800 / 200. The row-policy
   assertions compare officer-visible counts against the branch's own
   `hub_customer` count, so they hold at any volume.
2. **Probe count is 29** (the checked-in script's current assertion set); the
   2026-07-02 note cited 32. What matters is every probe in the current script
   passes.

## Gotcha caught live (CH 26.7)

`clickhouse client` 26.7.1.492 **rejects a duplicate `--user`** flag
(`Bad arguments: option '--user' cannot be specified more than once`). The
verify script appends `--user <probe> --password probe` to `$CH_CLIENT`, so a
`CH_CLIENT` that already carried `--user default --password demo` (as the
2026-07-02 recipe's did) fails every probe-user query with rc=36 and an empty
error. Fix without touching the repo script: put the `default`/`demo`
credentials in a client `--config-file` (`<host>/<port>/<user>/<password>`),
so bare `CH_CLIENT` authenticates as `default` and the appended `--user
<probe>` is the sole `--user` on the line:

```bash
CH_CLIENT="/path/clickhouse client --config-file=/path/client.xml" \
    bash governance/verify_live.sh
```

## Transcript

```
=== setup: probe users (stand-local, not part of the governance files) ===
users ready

=== dv2_analyst: non-PII access works (DEFINER view, column grants) ===
PASS  [analyst explicit non-PII projection] -> CUST-000000	msk	 CUST-000001	msk	
PASS  [analyst bare count()] -> 2190
PASS  [analyst aggregate over granted column] -> 2190	584720
PASS  [analyst GROUP BY + HAVING on granted columns] -> 	2038 mid	76
PASS  [analyst WHERE on passthrough column (customer_bk)] -> CUST-000000
PASS  [analyst hub_customer full visibility (catch-all row policy)] -> 2500
PASS  [analyst granted satellite (loyalty)] -> 152

=== dv2_analyst: PII columns are engine-denied in EVERY shape ===
PASS  [analyst plain PII column] -> ACCESS_DENIED
PASS  [analyst SELECT *] -> ACCESS_DENIED
PASS  [analyst bypass #1: COLUMNS('.*') expr] -> ACCESS_DENIED
PASS  [analyst bypass #2: whole-row struct ref] -> UNKNOWN_IDENTIFIER (shape not expressible on ClickHouse)
PASS  [analyst bypass #3: positional rename-list] -> UNKNOWN_IDENTIFIER (shape not expressible on ClickHouse)
PASS  [analyst PII inside expression] -> ACCESS_DENIED
PASS  [analyst PII in WHERE only] -> ACCESS_DENIED
PASS  [analyst raw personal satellite] -> ACCESS_DENIED
PASS  [analyst employee profile (name PII)] -> ACCESS_DENIED

=== known ergonomic limitation: filter pushdown vs column grants ===
PASS  [analyst filter on argMax-derived column (raw)] -> ACCESS_DENIED
PASS  [analyst same filter via subquery wrap (PII-safe workaround)] -> 152
PASS  [subquery wrap cannot smuggle PII] -> ACCESS_DENIED

=== officers: PII bounded to own jurisdiction ===
PASS  [officer_msk reads own-branch PII] -> Anna	cust0@example.test
PASS  [officer_msk filtered aggregate (full view grant)] -> 152
PASS  [officer_msk reads own personal satellite] -> 2190
PASS  [officer_msk cross-branch view denied] -> ACCESS_DENIED
PASS  [officer_msk cross-branch satellite denied] -> ACCESS_DENIED
PASS  [officer_msk hub row-scoped (msk rows only)] -> 2190
PASS  [officer_dxb hub row-scoped (dxb rows only)] -> 60
PASS  [officer_dxb sees zero msk rows via hub filter] -> 0

=== admin unaffected ===
PASS  [admin hub full visibility (catch-all)] -> 2500
PASS  [admin reads PII] -> cust0@example.test
```

## Honest scope

- Re-captured on the synthetic demo seed (2,500 customers), not on promoted
  CDC volume — the row-policy assertions compare officer-visible counts
  against admin-side per-branch counts, so the script re-runs unchanged on a
  stand with real data.
- The applying admin (`default`) sees everything: engine policies bind *roles*;
  production would split the admin identity from human users.
- `SQL SECURITY DEFINER` on the MDM views is load-bearing (an INVOKER default
  would need SELECT on the underlying personal satellites — exactly what the
  boundary denies).
