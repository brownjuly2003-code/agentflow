# DV2 Vault Governance on PostgreSQL — engine-enforced PII boundary

PostgreSQL port of the ClickHouse governance layer (`../../governance/`,
ADR 0006 Phase 2): roles, fail-closed allow-list grants and row-level
security that make customer contact PII **bounded on the engine**. Same
model, same object surface, translated to PostgreSQL semantics — the
differences are listed below, because several of them are load-bearing.

## Roles

| Role | Purpose | Contact PII |
| ---- | ------- | ----------- |
| `dv2_analyst` | Cross-branch analytics over hubs/links/non-PII satellites and business vault | **None.** Column-limited on `bv_customer_mdm__*` (no `first_name`/`last_name`/`email`/`phone`/`birth_date`); no grants on `sat_customer_personal__1c__*` or `sat_employee_profile__1c_zup__msk` |
| `dv2_pii_officer__<branch>` (msk/spb/ekb/dxb/ala) | PII steward of ONE jurisdiction | Own branch only: full columns on `bv_customer_mdm__<branch>` + `sat_customer_personal__1c__<branch>`; `hub_customer` row-scoped to the branch |

Users are stand-specific and not created here: create one LOGIN user per
deployment and `GRANT dv2_analyst TO <user>` (or an officer role).

## Files (apply in order, after apply.sh)

1. `01_roles.sql` — roles (DO-block idempotent; `CREATE ROLE` has no
   `IF NOT EXISTS`) + the mandatory `USAGE` on schema `rv`.
2. `02_grants_analyst.sql` — **fail-closed allow-list** for `dv2_analyst`.
   A new vault object is invisible to analysts until classified and added;
   `tests/unit/test_dv2_postgres_governance_ddl.py` forces every postgres
   satellite to be either granted or listed in the `DENIED` block.
3. `03_grants_pii_officers.sql` — per-jurisdiction officer grants.
4. `04_row_policies.sql` — `ENABLE ROW LEVEL SECURITY` on `rv.hub_customer`,
   branch policies for the officer roles, and the analyst catch-all.

```bash
PSQL="psql -h <host> -U <admin> -d agentflow"
for f in governance/0*.sql; do $PSQL -v ON_ERROR_STOP=1 -f "$f"; done
```

`apply.sh` does not auto-apply this layer (same rule as the ClickHouse
`governance/` — it depends on the business-vault views existing). Apply
manually after `apply.sh`, as the vault owner or a superuser.

## PostgreSQL vs ClickHouse — the differences that matter

- **RLS is default-deny.** Once `ENABLE ROW LEVEL SECURITY` is on the hub, a
  principal addressed by NO policy sees zero rows (verified live with a
  grant-only probe user). There is no
  `users_without_row_policies_can_read_rows` server flag to worry about — but
  the flip side is that every future role that should read the hub must be
  classified into a policy in `04_row_policies.sql`. Fail-closed, like the
  allow-list.
- **The catch-all must not be `TO PUBLIC`.** Permissive policies combine with
  OR and every role is a member of PUBLIC — a PUBLIC catch-all would OR
  `USING (true)` into the officer policies and void the jurisdiction scoping.
  `jurisdiction__all` addresses `dv2_analyst` explicitly (the ClickHouse
  original expresses the same intent as `TO ALL EXCEPT <officers>`).
- **`ENABLE`, never `FORCE`.** The table owner bypasses RLS under `ENABLE`.
  The `bv_customer_mdm__*` views execute with their owner's rights
  (PostgreSQL's default for views — the `SQL SECURITY DEFINER` analog;
  `security_invoker` is never set on them, pinned by the unit test), so the
  views read the full hub and pin their branch in their own `WHERE`. Under
  `FORCE` the owner-executed views would be policy-filtered and return zero
  rows for every reader.
- **The ClickHouse ergonomic limitation is absent.** Filtering on an
  SCD2-collapsed view column (`WHERE loyalty_segment = 'gold'`, `FILTER`
  aggregates) works directly for the column-limited role — no subquery-wrap
  workaround needed. Privileges are checked on the view's own attributes.
- **More SQL shapes exist here, and all of them are denied.** Whole-row refs
  (`SELECT t FROM view t`, `to_jsonb(t)`) and positional rename-lists
  (`AS t(a,b,...)`) are valid PostgreSQL (ClickHouse cannot parse them);
  they resolve to real attributes and fail with `permission denied` because
  the attribute ACL, not the output name, is what is checked.
- **Block comments nest.** A literal `/*`-containing glob inside a header
  comment swallows the rest of the file with `unterminated /* comment` at
  apply time (caught live; pinned by `test_no_nested_block_comments`).
- **Roles are cluster-wide, grants are per-database.** Re-applying to a
  second database on the same cluster reuses the roles and re-issues the
  grants; everything is idempotent (DO-block roles, additive grants,
  `DROP POLICY IF EXISTS` + `CREATE`).

## What this does NOT cover (honest scope)

- **The admin/owner sees everything.** Engine policies bound *roles*; the
  vault owner and superusers bypass them. Production would split the admin
  identity from human users (same note as the ClickHouse layer).
- **dbt marts and `bv_order_canonical_mat`** exist only on the ClickHouse
  stand; nothing to govern here.
- Live verification evidence:
  `docs/perf/vault-pii-governance-pg-verify-2026-07-02.md`; re-run the full
  deny/allow matrix on any stand with
  `PSQL="psql -h <host> -U <admin> -d agentflow" bash verify_live.sh`
  (add `SEED_DEMO=1` on an empty stand to exercise row scoping).
