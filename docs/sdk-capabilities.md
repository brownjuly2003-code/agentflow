# SDK capability contract

Generated from [`config/project_claims.toml`](../config/project_claims.toml). Edit the manifest, not this table.

| Capability | Python methods | TypeScript methods |
| --- | --- | --- |
| entity and historical reads | `get_entity`, `get_order`, `get_user`, `get_product`, `get_session` | `getEntity`, `getOrder`, `getUser`, `getProduct`, `getSession` |
| metric and historical reads | `get_metric` | `getMetric` |
| query, cursor, and pagination | `query`, `paginate` | `query`, `paginate` |
| query explanation | `explain_query` | `explainQuery` |
| semantic search | `search` | `search` |
| contract lifecycle | `list_contracts`, `get_contract`, `diff_contracts`, `validate_contract` | `listContracts`, `getContract`, `diffContracts`, `validateContract` |
| lineage and changelog | `get_lineage`, `get_changelog` | `getLineage`, `getChangelog` |
| health, catalog, batch, and resilience | `health`, `is_fresh`, `catalog`, `batch`, `configure_resilience` | `health`, `isFresh`, `catalog`, `batch`, `configureResilience` |
