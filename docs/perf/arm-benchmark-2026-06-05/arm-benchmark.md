# AgentFlow Benchmark Report

> This file is overwritten by the latest long-running benchmark. For entity-specific optimization evidence, see `docs/perf/entity-benchmark-contract.md`.

Generated: `2026-06-05T11:41:33+00:00`

## System Under Test

- OS: `Linux-6.17.0-1015-azure-aarch64-with-glibc2.39`
- CPU: `aarch64` (4 logical cores)
- RAM: `15.6 GB`
- Python: `3.11.15`

## Test Parameters

- Host: `http://127.0.0.1:8001`
- Seed step: `python -m src.processing.local_pipeline --burst 500`
- Load profile: `50` users, spawn rate `10/s`, duration `60s`
- Warmup: `10s` discarded pre-run with the same Locust traffic mix to reduce cold-start noise.
- Locust file: `tests/load/locustfile.py`

## Results

| Endpoint | Requests | Failures | Failure Rate | RPS | p50 | p95 | p99 |
|----------|----------|----------|--------------|-----|-----|-----|-----|
| ALL | 554 | 0 | 0.00% | 37.41 | 6.0 ms | 44.0 ms | 150.0 ms |
| POST /v1/batch | 108 | 0 | 0.00% | 7.29 | 8.0 ms | 87.0 ms | 150.0 ms |
| GET /v1/entity/order/{id} | 84 | 0 | 0.00% | 5.67 | 4.0 ms | 34.0 ms | 130.0 ms |
| GET /v1/entity/product/{id} | 72 | 0 | 0.00% | 4.86 | 4.0 ms | 33.0 ms | 84.0 ms |
| GET /v1/entity/user/{id} | 45 | 0 | 0.00% | 3.04 | 4.0 ms | 32.0 ms | 150.0 ms |
| GET /v1/metrics/{name} | 147 | 0 | 0.00% | 9.93 | 5.0 ms | 35.0 ms | 120.0 ms |
| POST /v1/query | 98 | 0 | 0.00% | 6.62 | 8.0 ms | 100.0 ms | 150.0 ms |

## Release Gate Context

- README no longer carries a benchmark claim table, so this run is compared against the release gate instead of documentation copy.
- Measured aggregate: p50 6.0 ms, p99 150.0 ms.
- Release gate for `/v1/entity/*`: p50 < 100 ms and p99 < 500 ms.
- Slowest entity endpoint in this run: `GET /v1/entity/user/{id}` at p50 4.0 ms, p99 150.0 ms.
- Aggregate throughput was 37.41 RPS with `50` concurrent users.

## Notes

- Benchmark comparability: this run matches or exceeds the canonical baseline (50 users, spawn rate 10/s, duration 60s).
- This report is generated from a fresh DuckDB dataset on every run.
- Re-running `python scripts/run_benchmark.py` overwrites this file with new measurements.
