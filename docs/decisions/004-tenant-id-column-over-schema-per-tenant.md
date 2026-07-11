# ADR-004: A `tenant_id` column, not a schema per tenant

## Status
Accepted (2026-07-11). Supersedes the implicit schema-per-tenant model that
`src/tenancy.py` and `SQLBuilderMixin` carried until now.

## Context

Tenant isolation was expressed as **schema qualification**: `TenantRouter` mapped
a tenant to a `duckdb_schema` (`acme-corp` → `acme`), and `SQLBuilderMixin`
rewrote every table reference into `"acme"."orders_v2"`. That was the only
mechanism. It does not work, on either store:

- **On ClickHouse** the same qualification names a *database* `acme` that nothing
  creates, so an entity read raises `UNKNOWN_TABLE`. Drop the qualification and
  every tenant shares one table — and, worse, one `ReplacingMergeTree` key: two
  tenants' rows with the same `order_id` are two *versions of one row*, so the
  later insert destroys the earlier one. That is data loss, not just a leak, and
  no read-side filter can undo it.
- **On DuckDB** nothing in `src/` ever issues `CREATE SCHEMA` — only four test
  fixtures do. So the tenant schema does not exist at runtime, and an
  authenticated request dies on a relation that was never created. Measured on
  the shipped config, before this change:

  ```
  get_entity(tenant=None)        -> HIT ORD-20260404-1001     # auth disabled
  get_entity(tenant='acme-corp') -> ValueError: Table '"acme"."orders_v2"' ... not materialized
  ```

  Every key in `config/api_keys.yaml` carries `tenant: "acme-corp"`, so *every*
  authenticated entity read was failing. The suite did not catch it because its
  API tests disable auth or create the schemas by hand.

Meanwhile the journal (`pipeline_events`) had already moved to a different model
— a `tenant_id` column plus a predicate (`JournalReader._tenant_predicate`) —
and that one works on both stores. The platform was running two isolation
models, and the one used for entities, metrics and NL was the broken one.

## Decision

**One model, both stores: a `tenant_id` column, in the write key, with a tenant
predicate on every read.**

- `tenant_id` is a column on all five serving tables.
- It **leads the write key**: `ORDER BY (tenant_id, <pk>)` on ClickHouse
  (`ReplacingMergeTree`), `PRIMARY KEY (tenant_id, <pk>)` on DuckDB (the pipeline
  upserts with `INSERT OR REPLACE`, which resolves against it). Two tenants that
  share an entity id are two rows, not two versions of one.
- Reads go through one chokepoint. `SQLBuilderMixin._qualify_table` returns a
  scoped *relation*, not a name:

  ```sql
  (SELECT * EXCLUDE (tenant_id) FROM orders_v2 WHERE tenant_id = 'demo') AS "orders_v2"
  ```

  `_scope_sql` performs the same substitution inside metric templates and
  NL-generated SQL. `EXCLUDE` keeps `tenant_id` out of `SELECT *`, so API
  responses keep exactly the columns the entity contract promises and the two
  stores stay column-identical. sqlglot transpiles `EXCLUDE` → ClickHouse's
  `EXCEPT` and the existing `_assert_scope_preserved` guard still holds, because
  the table reference inside the sub-select is unchanged.
- Writes stamp the tenant: `event_tenant()` (leaf module, shared by the pipeline
  and the ClickHouse sink) resolves it from the event, defaulting to `'default'`.
- Aggregates group by it. `refresh_user_aggregates` takes `(tenant, user)` pairs
  and groups by `tenant_id, user_id`; a global `GROUP BY user_id` would have
  summed two tenants' orders into one total and written it back to both.
- Schema-per-tenant is **gone**, not kept as a second layer. `duckdb_schema` is
  removed from `TenantDefinition`, from `config/tenants.yaml` and from the chart's
  shipped values, and `TenantRouter.get_duckdb_schema()` is deleted: a field that
  names an isolation boundary, that nothing reads and that nothing provisions, is
  a trap for whoever configures the next tenant. Two compatibility seams remain,
  deliberately: pydantic ignores unknown keys, so an existing `config/tenants.yaml`
  still loads; and the Helm values schema still *accepts* `duckdb_schema` (tenant
  items are `additionalProperties: false`, so dropping it outright would reject
  values written for the old model) with a description saying it is ignored.
  Accepted and inert, not required and pretending.

`tenant_id = NULL` means an unscoped read — but not an unconditional one. The
fail-closed guard survives the model change: if the table holds rows of any
tenant other than the default one and no tenant context was resolved, the read is
**refused** (503, "Tenant context is required"), because answering it would hand
the caller every tenant's data. A single-tenant store — everything under
`DEFAULT_TENANT`, which is what a deployment that never names a tenant produces —
has nothing to leak and stays readable. One probe per table per process, cached,
exactly like the `_table_columns` probe the old guard used.

The old guard asked the same question of the schema model ("does a tenant's copy
of this table physically exist?"). It could not be kept verbatim: in the column
model *every* table is tenant-scoped, so a guard keyed on the config alone would
fail-closed on the single-tenant demo too.

`DEFAULT_TENANT` lives in `src/tenancy.py` — the one module both the write path
(`src/processing/event_tenant.py`) and the read path (`SQLBuilderMixin`) can reach
without importing each other.

## Comparison

| | `tenant_id` column (chosen) | Database/schema per tenant |
|---|---|---|
| Works on ClickHouse | Yes | Only if router, sink, provisioning and migrations all route DDL and DML per tenant — none do |
| Works on DuckDB | Yes | No — nothing creates the schemas |
| Protects the write key | Yes — tenant leads the sorting/primary key | Yes, implicitly (separate tables) |
| Cost of a new tenant | Zero (a value) | DDL per tenant, on every table, in every store |
| Cross-tenant admin query | Natural (drop the predicate) | Needs a UNION over N schemas |
| Blast radius of a missing predicate | A leak (bounded by the read chokepoint) | N/A |
| Consistent with the existing journal | Yes — same model | No — journal already used the column |

## Consequences

### Positive
- Isolation that is actually provisioned, on both stores, and provable against a
  live ClickHouse with two tenants holding identical entity ids.
- Authenticated entity reads work at all (they did not, before).
- One model to reason about, one place to enforce it, one thing to test.
- Adding a tenant is a config line, not a migration.

### Negative
- The predicate is load-bearing: a read surface that bypasses `_qualify_table` /
  `_scope_sql` sees every tenant. Mitigated by making them the only way in, and
  by an adversarial test that plants two tenants with identical ids and asserts
  no read surface ever crosses over.
- The search index is one corpus for all tenants (it is built once per process),
  so the tenant travels on the document and is filtered before scoring. Term
  statistics (`idf`) are still computed corpus-wide: a tenant's *ranking* can be
  influenced by the vocabulary of other tenants' rows, though no document, id or
  snippet of theirs can be returned. Per-tenant indexes would fix the former at
  the cost of rebuilding the corpus once per tenant; not worth it today, and
  noted so it is a decision rather than an oversight.
- ClickHouse cannot prepend a column to an existing sorting key, and
  `CREATE TABLE IF NOT EXISTS` silently keeps the old one. A store provisioned
  before this change must be rebuilt.

### Migration
- ClickHouse: `python -m src.serving.provision --migrate` — stages a table with
  the new key, copies rows in under the `'default'` tenant (`FINAL`, so
  ReplacingMergeTree versions collapse first), and `EXCHANGE TABLES` atomically.
  Idempotent; re-running after it completes is a no-op.
- DuckDB: no in-place migration (a PRIMARY KEY cannot be altered). Only a
  file-backed store is affected; delete it and re-run `--schema`. `:memory:` —
  the default — is created correctly every boot.
- Both `ensure_schema()` implementations **refuse to serve** a store that still
  has the old key, naming the fix. Silence there was the whole failure mode.

### Config that had to be aligned
Demo keys in `config/api_keys.yaml` carried `tenant: "acme-corp"` while the demo
seed — and the live demo stream, via `event_tenant()`'s `'default'` fallback —
write under `'default'`. Under auth those keys would see an empty store. They now
carry `tenant: "default"`: the demo is single-tenant, and its keys name the tenant
its data is actually under. Aligning the config is the fix; weakening the boundary
is not.

This mismatch was invisible before, and the reason is worth recording. The
shipped keys named `acme-corp`, and the test keys named `acme` — a tenant that
does not appear in `config/tenants.yaml` at all. `get_duckdb_schema()` therefore
returned `None` for it, the qualification was skipped, and the read fell through
to the shared table. The suite was green *because* the scoping silently did
nothing. A boundary that no test can tell apart from its own absence is not a
boundary.
