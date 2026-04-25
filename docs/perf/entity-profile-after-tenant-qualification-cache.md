# Entity Profile After Tenant Qualification Cache

**HEAD measured:** `5b57cf4020f8c7f0138e313d47ab644c2b33f6a4`
**Hypothesis:** cache tenant config and resolved table qualification
**Decision:** accepted - p99 improved by 42.13%, above the 5% threshold.

## Summary

T24 targeted the post-PII hot frame cluster from `docs/perf/entity-profile-2026-04-24.md`: repeated tenant config loading, no-tenant table qualification, and DuckDB table-column probes on the entity endpoint.

The implementation caches:

- `TenantRouter.has_config()` and parsed `TenantRouter.load()` results per router instance.
- `QueryEngine._table_columns()` results per engine instance.
- successful `_qualify_table(table_name, resolved_tenant_id)` results per engine instance.

The benchmark used the contract parameters: `/v1/entity/order/ORD-20260404-1001`, 2000 iterations, concurrency 16, warmup 20, API on `127.0.0.1:8000`, Redis up, open auth (`configured_keys=0`), DuckDB `agentflow_demo.duckdb`.

## Best-of-3 Result

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| p50_ms | 193.29 | 113.01 | -41.53% |
| p95_ms | 242.42 | 140.88 | -41.89% |
| p99_ms | 288.85 | 167.14 | -42.13% |
| throughput_rps | 81.10 | 138.08 | +70.26% |
| wall_seconds | 24.662 | 14.485 | -41.27% |

Artifacts:

- `docs/perf/entity-latency-before-tenant-qualification-cache.json`
- `docs/perf/entity-latency-after-tenant-qualification-cache.json`

## Reproducibility Note

Both before and after sets had p99 spread above the contract's preferred 10% noise band. The run logs showed no `query_cache_unavailable` warnings or server errors. Despite the spread, every after run beat the best before p99 by more than the 5% acceptance threshold; the worst after p99 was 261.46 ms versus the best before p99 of 288.85 ms.
