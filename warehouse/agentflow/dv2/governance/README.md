# DV2 Vault Governance — engine-enforced PII boundary (ADR 0006 Phase 2)

ClickHouse RBAC objects (roles, grants, row policies) that make customer
contact PII **bounded on the engine**. This replaces the removed serving-layer
string-parse gate (`assert_no_pii_access`, see CHANGELOG 2026-07-01): instead
of guessing which SQL shapes can reach a PII column, the column is simply not
granted — `SELECT *`, `SELECT COLUMNS('.*')`, whole-row struct refs and
positional rename-lists (`AS t(a, b, ...)`) all fail with `ACCESS_DENIED`
because access control runs on resolved columns, not on SQL text.

## Roles

| Role | Purpose | Contact PII |
| ---- | ------- | ----------- |
| `dv2_analyst` | Cross-branch analytics over hubs/links/non-PII satellites, business vault and marts | **None.** Column-limited on `bv_customer_mdm__*` (no `first_name`/`last_name`/`email`/`phone`/`birth_date`); no grants on `sat_customer_personal__1c__*` or `sat_employee_profile__1c_zup__msk` |
| `dv2_pii_officer__<branch>` (msk/spb/ekb/dxb/ala) | PII steward of ONE jurisdiction | Own branch only: full columns on `bv_customer_mdm__<branch>` + `sat_customer_personal__1c__<branch>`; `hub_customer` row-scoped to the branch |

Users are stand-specific and not created here: create one per deployment and
`GRANT dv2_analyst TO <user>` (or an officer role).

## Files (apply in order, after raw vault + business vault)

1. `01_roles.sql` — roles.
2. `02_grants_analyst.sql` — **fail-closed allow-list** for `dv2_analyst`.
   A new vault object is invisible to analysts until classified and added;
   `tests/unit/test_dv2_governance_ddl.py` forces every raw_vault satellite to
   be either granted or listed in the `DENIED` block of that file.
3. `03_grants_pii_officers.sql` — per-jurisdiction officer grants.
4. `04_row_policies.sql` — branch row policies on `rv.hub_customer` + the
   mandatory catch-all.

```bash
for f in governance/*.sql; do
  cat "$f" | clickhouse-client --user default --password demo --multiquery
done
```

`infrastructure/dv2/bootstrap.sh` does not auto-apply this layer (same rule as
`business_vault/` — it depends on the business vault views being applied
first). Apply manually after the business vault loop.

## Design decisions

- **Allow-list, not deny-list.** `GRANT SELECT ON rv.*` + partial `REVOKE`
  would be fail-open: the next PII table added to the vault would be readable
  by default. Explicit grants are verbose by design — the file is the
  reviewable governance manifest.
- **`SQL SECURITY DEFINER` on `bv_customer_mdm__*`.** ClickHouse normal views
  default to INVOKER security, so a reader would need SELECT on the underlying
  personal satellites — the exact tables the boundary denies. With DEFINER the
  view body runs under the definer's rights and the column-limited grant on
  the view is sufficient. Consequence: row policies of the *reader* do not
  re-filter inside the view (the definer reads the hub); each view pins its
  branch in its own WHERE, so this is by construction, not by policy.
- **Row policies govern direct `hub_customer` reads.** The hub is the one
  shared customer table (branch lives in `record_source`); officers are scoped
  to their jurisdiction there. **Gotcha:** whether principals not addressed by
  any policy still see rows depends on the server flag
  `access_control_improvements.users_without_row_policies_can_read_rows`
  (true on modern default configs, false on configs carried over from older
  servers — there it silently hides all rows). The `jurisdiction__all`
  catch-all pins full hub visibility for non-officers independent of that
  flag; never drop it.
- **Marts are PII-free by contract.** `marts.customer_360` is cross-branch and
  materialized; carrying contact fields would copy jurisdiction-bound PII out
  of its branch and past the column grants at build time. The model drops them
  (see the header of `dbt/models/marts/customer_360.sql`); analysts keep
  `pii_source` metadata.
- **`access_management`.** Applying these files requires an admin identity
  with `access_management=1` (`CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: "1"` in
  `infrastructure/dv2/clickhouse-sts.yaml`; rebuilt stands pick it up
  automatically, an existing stand needs a pod restart).

## Known ergonomic limitation (verified live on 26.7)

A filter expression (`WHERE`, `HAVING` over source columns, `-If` aggregate
combinators) that references a view column derived through an **aggregation or
rename inside the view** (the `argMax(...)` columns: `loyalty_segment`,
`loyalty_points`, `last_visit_at`, ...) is pushed down past the view boundary,
cannot be attributed back to granted view columns, and falls back to demanding
a table-level `SELECT` on the view — so it fails with `ACCESS_DENIED` for the
column-limited `dv2_analyst` even though the column itself is granted. Plain
projections, aggregates, `GROUP BY`/`ORDER BY`/`HAVING` on aggregate aliases,
and `WHERE` on passthrough columns (`customer_bk`, `customer_hk`) or literals
(`branch`) are unaffected.

Workaround — wrap the projection in a subquery so the filter applies above it:

```sql
SELECT count() FROM (SELECT loyalty_segment FROM rv.bv_customer_mdm__msk)
WHERE loyalty_segment = 'gold';
```

This is PII-safe: the inner projection is itself column-checked (swapping in
`email` fails with `ACCESS_DENIED`). Verified in the evidence transcript. For
unrestricted slicing analysts should prefer `marts.customer_360` (full-table
grant, PII-free by contract).

## What this does NOT cover (honest scope)

- **The PostgreSQL port** (`../postgres/03_business_vault.sql`) has the same
  MDM views but no equivalent policy set yet (PG RLS + column grants would be
  the analog). The ClickHouse vault is the demo/serving path; the PG port is
  a source-replica used by the CDC demo. Follow-up, not shipped.
- **`default` is superuser.** The demo admin (`default`/`demo`) sees
  everything — engine policies bound *roles*, they do not remove the admin.
  Production would split the admin identity from human users.
- Live verification evidence: `docs/perf/vault-pii-governance-verify-2026-07-02.md`;
  re-run the full deny/allow matrix on any stand with `verify_live.sh`
  (`CH_CLIENT="clickhouse-client --user default --password demo" bash verify_live.sh`).
