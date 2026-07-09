# Q1.1 / Q1.2 — bridge write path: CH-native apply (code slice)

**Date:** 2026-07-09  
**Code:** `skip_local_store` on ClickHouse bridge path  
**Live re-measure:** pending Mac/Colima (`scripts/benchmark_throughput_realpath.py`)

## Diagnosis (Q1.1, from code + S10)

S10 measured **~8 events/s** bridge apply on real path. Apply loop:

```
for event in batch:
    _process_event(scratch_duckdb, event, clickhouse_sink=sink)
```

`_process_event` on the dual-write path did, **per event**:

1. DuckDB `BEGIN`
2. validate + enrich
3. DuckDB upserts (`orders_v2`, `users_enriched`, journal, …)
4. DuckDB `COMMIT`
5. ClickHouse HTTP: upsert order + status journal + events.validated journal
   (+ user aggregate recompute SELECT/INSERT on CH)

The API never reads the bridge scratch lake (guard already queries **serving**
journal — S6 design). Steps 1–4 were pure cost on the production path.

## Change (Q1.2 first slice)

| Path | Behaviour |
|------|-----------|
| Bridge + `sink is not None` | `_process_event(..., skip_local_store=True)` → `_process_event_serving_only` |
| Bridge DuckDB demo / tests | unchanged (lake + optional write lock) |
| `local_pipeline` dual-write | unchanged (demo still mirrors CH after DuckDB commit) |

Idempotency, offset-after-apply, and dead-letter semantics unchanged.
Unit pin: `test_clickhouse_path_skips_scratch_duckdb_on_apply`.

## Q1.3 follow-up (same day)

- `apply_serving_batch`: multi-row order + journal inserts; aggregate once per
  unique user; journal last for crash-replay safety.
- Still sequential: session RMW, Flink hop.

## Expected effect

| Hypothesis | How to falsify |
|------------|----------------|
| Scratch DuckDB was a large fraction of the 8 eps | S10 re-run apply rate jumps materialy (×2+) |
| CH HTTP multi-call dominates | Rate stays ~8–15 eps → next: batch insert + amortize aggregate |

## Verify

```bash
# Unit (Windows-safe)
pytest tests/unit/test_serving_bridge.py tests/unit/test_local_pipeline_clickhouse_mirror.py -p no:schemathesis -q

# Live (Mac)
python scripts/benchmark_throughput_realpath.py ...
# write docs/perf/throughput-realpath-2026-….md next to the old 8 eps report
```
