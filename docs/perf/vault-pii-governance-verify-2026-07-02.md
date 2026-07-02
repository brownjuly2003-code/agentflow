# DV2 vault PII governance — live verification (ADR 0006 Phase 2)

**Date:** 2026-07-02
**Environment:** standalone `clickhouse server` 26.7.1.368 (single binary, WSL
Ubuntu 22.04, no Docker), `access_management=1` for the applying admin user —
the same standalone setup that verified the Phase 1 serving flip
(`clickhouse-serving-verify-2026-07-02.md`). Vault built from the repo files
verbatim: `__init.sql` → hubs → links → all 48 satellites →
`synthetic_seed.sql` + `satellite_seed.sql` + `satellite_seed_all_branches.sql`
(hub_customer: msk 800 / spb 500 / ekb 300 / dxb 200 / ala 200 = 2000 rows) →
`business_vault/*.sql` (views with `SQL SECURITY DEFINER`) →
`governance/01..04.sql`. Probe users are stand-local: `analyst_probe`
(role `dv2_analyst`), `officer_msk_probe`, `officer_dxb_probe`.

**Result: 32/32 probes passed.** The PII boundary is enforced by the engine's
access control on resolved columns — there is no SQL shape that reaches an
ungranted PII column.

## What the engine denies for `dv2_analyst` (column-limited)

| Probe | Result |
| ----- | ------ |
| `SELECT email FROM rv.bv_customer_mdm__msk` | `ACCESS_DENIED` (497) |
| `SELECT *` | `ACCESS_DENIED` |
| Historical bypass #1: `SELECT COLUMNS('.*')` | `ACCESS_DENIED` |
| Historical bypass #2: whole-row struct ref `SELECT t FROM ... AS t` | `UNKNOWN_IDENTIFIER` (47) — the DuckDB shape is not expressible on ClickHouse |
| Historical bypass #3: positional rename-list `AS t(a,b,...)` | `UNKNOWN_IDENTIFIER` (47) — not expressible |
| PII inside expression `upper(email)` | `ACCESS_DENIED` |
| PII in WHERE only (`SELECT customer_bk ... WHERE email LIKE '%@%'`) | `ACCESS_DENIED` |
| Raw `sat_customer_personal__1c__msk` (no grant) | `ACCESS_DENIED` |
| `sat_employee_profile__1c_zup__msk` (employee names, no grant) | `ACCESS_DENIED` |

The three historical bypass forms of the removed app-level string-parse gate
(cont.33) are dead here **by construction**: two of them don't parse on this
engine at all, and the one that does (`COLUMNS`) still has to resolve to real
columns, at which point the missing grant denies it. This is the difference
between denying SQL shapes and not granting columns.

## What works for `dv2_analyst`

Explicit non-PII projections, bare `count()`, `count(col)`/`sum(col)`,
`GROUP BY`/`ORDER BY`/`HAVING` on aggregate aliases, `WHERE` on passthrough
columns (`customer_bk LIKE 'CUST-0001%'`) and literal-derived columns
(`branch = 'msk'`), full `hub_customer` visibility (catch-all row policy,
2000 rows), granted satellites, and `marts.customer_360` with arbitrary
filtering (full-table grant, PII-free by contract — `system.columns` confirms
zero contact-PII columns in the built mart; built from the rendered dbt model).

## Jurisdiction scoping (row policies + per-branch grants)

| Probe | Result |
| ----- | ------ |
| officer_msk reads own-branch PII (`first_name, email` from msk view) | rows |
| officer_msk filtered aggregate on full-grant view | works (no column-limit in play) |
| officer_msk reads `sat_customer_personal__1c__msk` | 800 |
| officer_msk on dxb view / dxb satellite | `ACCESS_DENIED` |
| officer_msk direct `hub_customer` scan | **800** (row policy: msk only) |
| officer_dxb direct `hub_customer` scan | **200** (dxb only) |
| officer_dxb `countIf(branch = 'msk')` on hub | **0** |
| `default` admin hub scan / PII read | unaffected (2000 / rows) |

## Row-policy flag counterfactual

Dropping the `jurisdiction__all` catch-all left `default` reading all 2000 hub
rows — i.e. on 26.7 the effective
`access_control_improvements.users_without_row_policies_can_read_rows` is
**true** (unaddressed principals keep reading). On configs carried over from
older servers the flag is false and the same drop silently hides **all** rows
from every unaddressed principal. The catch-all is kept so the governance
layer behaves identically on both kinds of stands. Re-applying
`04_row_policies.sql` restored the exact state (idempotency check: 2000).

## Found and root-caused: filter pushdown vs column-limited grants

`SELECT countIf(loyalty_segment != '') FROM rv.bv_customer_mdm__msk` fails
with `ACCESS_DENIED` for `dv2_analyst` even though `loyalty_segment` is
granted. Root-caused by controlled A/B views on a scratch schema:

- filters on view columns that pass through **unrenamed from a base table**
  are fine (`WHERE customer_bk LIKE ...` works);
- filters on view columns derived through an **aggregation or rename inside
  the view** (`argMax(...) AS loyalty_segment`) are pushed past the view
  boundary, cannot be attributed back to granted view columns, and fall back
  to demanding table-level `SELECT` on the view → denied for column-limited
  principals. Granting the invoker the underlying base columns does **not**
  lift it (checked); a full-table view grant does (officer probes pass).

Ergonomic, not a hole — deny-direction only. PII-safe workaround verified:

```sql
SELECT count() FROM (SELECT loyalty_segment FROM rv.bv_customer_mdm__msk)
WHERE loyalty_segment = 'gold';   -- 160
```

The inner projection is itself column-checked: the same wrap with `email`
inside fails with `ACCESS_DENIED` (probed). Documented in
`governance/README.md`.

## Gotchas for the next operator

- Applying RBAC DDL needs `access_management=1` on the admin user
  (`CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: "1"` added to
  `infrastructure/dv2/clickhouse-sts.yaml`; an existing stand needs a pod
  restart, a rebuilt stand picks it up automatically).
- `SQL SECURITY DEFINER` on the MDM views is load-bearing: with the INVOKER
  default, a column-limited reader would need SELECT on the underlying
  personal satellites — exactly what the boundary denies — and every view
  read would fail.
- The whole matrix is re-runnable on any stand:
  `warehouse/agentflow/dv2/governance/verify_live.sh` (configure the client
  via `CH_CLIENT`); the governance SQL itself is idempotent
  (`IF NOT EXISTS` / additive `GRANT`).
