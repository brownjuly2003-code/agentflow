# How to add a new entity type

Entity types are registered through YAML files under
`contracts/entities/`. The four legacy types — `order`, `user`,
`product`, `session` — live there and are loaded at startup into the
`DataCatalog` that backs `/v1/entity/{type}/{id}`, the NL query engine,
and the search index.

## Required fields

```yaml
name: order                    # must match the file stem
description: Short human summary used for discovery and NL-query prompts.
table: orders_v2               # source table in the serving database
primary_key: order_id          # column used to resolve /v1/entity/{type}/{id}
fields:
  order_id: Unique order identifier
  user_id: Customer identifier
  status: "Current status: pending, confirmed, shipped, ..."
  # ...one entry per column the catalog should advertise
relationships:
  user: user_id                # optional: {target_entity: foreign_key}
```

The loader validates:

- All of `name`, `description`, `table`, `primary_key`, `fields` are
  present.
- `fields` is a non-empty mapping.
- `primary_key` is a key in `fields`.
- `name` in the file matches the file stem (so `order.yaml` must have
  `name: order`).
- `relationships`, if present, is a mapping.

If any file fails validation the process refuses to start. This is
intentional: a misconfigured catalog would silently break NL query and
entity lookup.

## Procedure

1. Drop a new `contracts/entities/<type>.yaml` on the repo root or
   mount it into the deployment in that path.
2. Make sure the source table exists in DuckDB (or the configured
   backend) and is allowlisted by `sqlglot` AST validation — any table
   referenced by a contract must also be discoverable by the SQL
   guard.
3. Restart the API process. The registry loads on startup, so a
   fresh process picks up the new file automatically.
4. Verify:
   - `curl http://localhost:8000/v1/catalog` lists the new type.
   - `curl http://localhost:8000/v1/entity/<type>/<id>` returns a
     valid response for a known id.
5. Consider adding a unit test under `tests/unit/` that asserts the
   new entity loads with the expected schema.

## Supported field "types"

The MVP loader preserves `fields` as a `dict[str, str]` where the
value is a human description. Typed field specs (`{type: enum,
values: [...]}`) are a follow-up — do not rely on them yet.

## Relationships

Relations are declarative-only in this version. They power discovery
in the catalog response and inform NL prompts, but the serving layer
does not auto-join on them. If you need auto-joins, file a follow-up
that extends the query planner.

## Versioning

Schema-level contract versions live in a separate registry
(`src/serving/semantic_layer/contract_registry.py`) and are keyed by
entity name. To bump a contract version for an entity:

1. Register the new version in the schema contract registry.
2. Keep the YAML file shape unchanged — the version is resolved at
   startup and attached to `EntityDefinition.contract_version`
   automatically.

Breaking schema changes should bump the version; non-breaking
additions (new column, new relationship) can stay on the existing
version.

## Gotchas

- Do not commit a YAML whose `table` refers to an unreleased source.
  The catalog will advertise the type even if the backing table is
  empty, which leads to confusing 500s from the query path.
- Avoid wide schemas in the catalog field map. Only list the columns
  the LLM should see; operational columns (e.g. internal watermarks)
  belong in the table, not the catalog.
- YAML indentation is significant. Two spaces per level.
