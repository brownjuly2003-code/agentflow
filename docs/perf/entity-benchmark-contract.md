# Entity Latency Benchmark Contract

**Version:** 1.0
**Date:** 2026-04-24
**Applies to:** `/v1/entity/{type}/{id}` hot path on current HEAD (`97a1902`)
**Replaces:** ad-hoc benchmark files (`docs/benchmark*.md`) as canonical reference.

## 1. Purpose

This document defines the **single repeatable way** to measure entity-endpoint latency before/after any perf change. Until this contract exists, conflicting benchmark artifacts (`benchmark_pool16.md`, `benchmark_pool16_60s.md`, etc.) produce non-comparable numbers and mislead optimization planning.

## 2. Required Stack & Services

A meaningful measurement **requires** the following services to be reachable. Running against a bare uvicorn process produces misleading numbers (see [docs/perf/README.md](README.md)).

| Service | Why required | Startup command |
|---------|--------------|-----------------|
| **Redis** | `QueryCache` logs `query_cache_unavailable` warnings to stderr on every request when Redis is down; at concurrency >= 8 this alone dominates latency. | `docker compose up -d redis` |
| **DuckDB (seeded)** | API reads from `agentflow_demo.duckdb`; must contain pipeline output + benchmark fixture rows. | `python -m src.processing.local_pipeline --burst 500` then seed fixtures via `scripts.run_benchmark.seed_benchmark_fixtures` |
| **API server** | Uvicorn serving `src.serving.api.main:app` on a known port. | `uvicorn src.serving.api.main:app --host 127.0.0.1 --port 8000` |

### Caveats / known noise sources

- **Kafka is NOT required** for the entity path itself, but `/v1/health` fans out to Kafka. If a health probe runs concurrently (e.g. from another terminal or Docker healthcheck), the event loop stalls for ~10 s while rdkafka retries the missing broker. Isolate the benchmark run from concurrent health checks.
- **Do not benchmark while `query_cache_unavailable` warnings appear in API logs.** You are measuring logging, not the serving path.
- The auth middleware writes to `agentflow_api.duckdb` (usage DB) on every request; this is single-writer DuckDB contention and is part of the current real latency profile.

## 3. Canonical Quick Profile

Use `scripts/profile_entity.py` for rapid hypothesis validation (< 1 min turnaround).

### Command

```bash
python scripts/profile_entity.py \
  --host http://localhost:8000 \
  --entity-type order \
  --entity-id ORD-20260404-1001 \
  --iterations 2000 \
  --concurrency 16 \
  --output docs/perf/entity-latency-<label>.json
```

### Parameters (locked)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `--iterations` | 2000 | Enough to stabilise p99; 1000 is too noisy on Windows. |
| `--concurrency` | 16 | Matches previously used pool size; high enough to expose contention, low enough to avoid event-loop saturation on this hardware. |
| `--warmup` | 20 (default) | DuckDB warm-up + connection pool stabilisation. |
| `--entity-type` / `--entity-id` | `order` / `ORD-20260404-1001` | Deterministic fixture row that exists in the seed dataset. |
| `--host` | `http://localhost:8000` | Default demo port; avoids collision with `run_benchmark.py` (8001). |

### Output schema

The JSON file must contain at minimum:

```json
{
  "url": "...",
  "iterations": 2000,
  "concurrency": 16,
  "warmup": 20,
  "wall_seconds": 29.166,
  "success_count": 2000,
  "failure_count": 0,
  "throughput_rps": 68.57,
  "p50_ms": 179.29,
  "p95_ms": 615.62,
  "p99_ms": 936.34,
  "max_ms": 1731.31,
  "mean_ms": 232.83
}
```

## 4. Canonical Full Benchmark

Use `scripts/run_benchmark.py` for release baseline and aggregate API-surface checks.

### Command

```bash
python scripts/run_benchmark.py \
  --users 50 \
  --spawn-rate 10 \
  --run-time 60s \
  --burst 500
```

This auto-starts the API on port 8001, seeds data, runs Locust warmup + measured window, and produces:

- `docs/benchmark.md` -- human-readable report
- `.artifacts/benchmark/current.json` -- machine-readable results

### Full-benchmark load profile (locked)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Users | 50 | Canonical from Locustfile mix (40 % entity). |
| Spawn rate | 10/s | Steady ramp; avoids cold-start thundering herd. |
| Run time | 60 s | Minimum for stable p99 on this hardware. |
| Burst seed | 500 | Populates DuckDB with realistic event volume. |

## 5. Machine Metadata Capture

Every baseline artifact must include:

```json
{
  "machine": {
    "os": "Windows-11-10.0.26200-SP0",
    "cpu": "Intel64 Family 6 Model 170 Stepping 4, GenuineIntel",
    "cpu_count": 18,
    "ram_gb": 15.5,
    "python": "3.13.7"
  },
  "stack": {
    "redis": "up (Docker)",
    "kafka": "down (not required for entity path, but noted)",
    "duckdb_path": "agentflow_demo.duckdb"
  }
}
```

`scripts/run_benchmark.py` already captures OS/CPU/RAM/Python. `scripts/profile_entity.py` does **not** capture machine metadata; the benchmark contract requires annotating the JSON file manually or via wrapper.

## 6. File Naming & Placement

| Artifact type | Pattern | Location |
|---------------|---------|----------|
| Quick profile JSON | `entity-latency-<label>.json` | `docs/perf/` |
| Full benchmark JSON | `benchmark-<label>.json` | `.artifacts/benchmark/` |
| Flamegraph | `flamegraph-<label>.svg` | `docs/perf/` |
| Profile write-up | `entity-profile-<label>.md` | `docs/perf/` |
| Release report | `benchmark.md` | `docs/` |

`<label>` conventions:

- `baseline` -- current HEAD before any change
- `after-<hypothesis>` -- after applying a specific hypothesis (e.g. `after-pii-masker-cache`)
- `date` -- for historical snapshots (`2026-04-24`)

## 7. Reproducibility Checklist

Before claiming a before/after delta:

- [ ] Redis is healthy (`docker ps` shows `Up`)
- [ ] DuckDB seeded and fixtures inserted
- [ ] API logs show **zero** `query_cache_unavailable` warnings during the run
- [ ] No concurrent health probes (`curl /v1/health`) running in another terminal
- [ ] Same machine, same power profile (no battery saver, no background builds)
- [ ] Quick profile runs back-to-back (before change -> after change) within 5 minutes
- [ ] Full benchmark runs back-to-back within 15 minutes
- [ ] Flamegraph captured during the same load window as the quick profile

## 8. Ground Rules for Hypothesis Validation

Inherited from T05 and reinforced by this re-baseline:

1. **5 % threshold:** If a change does not improve p99 by >= 5 % on the same hardware, drop it. Do not commit.
2. **Evidence first:** No optimization enters the sprint without a measured hot frame or latency regression linking it to the entity path.
3. **sqlglot cache is irrelevant for entity path:** `entity_queries.py` builds SQL with f-strings; sqlglot is not on the hot path. Any sqlglot-cache work must show wins on **other** endpoints (e.g. `/v1/query`) before it can be considered for entity.
