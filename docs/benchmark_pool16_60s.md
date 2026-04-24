# AgentFlow Benchmark Report

> **ARCHIVED -- Historical input only.**
> This report was produced with non-canonical parameters (50 users, 60 s) and is **not comparable** to the 2026-04-24 entity baseline. See `docs/perf/entity-benchmark-contract.md` for the current reference benchmark.

Generated: `2026-04-17T07:58:16+03:00`

## System Under Test

- OS: `Windows-11-10.0.26200-SP0`
- CPU: `Intel64 Family 6 Model 170 Stepping 4, GenuineIntel` (18 logical cores)
- RAM: `15.5 GB`
- Python: `3.13.7`

## Test Parameters

- Host: `http://127.0.0.1:8001`
- Seed step: `python -m src.processing.local_pipeline --burst 500`
- Load profile: `50` users, spawn rate `10/s`, duration `60s`
- Locust file: `tests/load/locustfile.py`

## Results

| Endpoint | Requests | Failures | Failure Rate | RPS | p50 | p95 | p99 |
|----------|----------|----------|--------------|-----|-----|-----|-----|
| ALL | 25 | 0 | 0.00% | 25.13 | 28.0 ms | 160.0 ms | 160.0 ms |
| POST /v1/batch | 2 | 0 | 0.00% | 2.01 | 160.0 ms | 160.0 ms | 160.0 ms |
| GET /v1/entity/order/{id} | 1 | 0 | 0.00% | 1.01 | 15.0 ms | 15.0 ms | 15.0 ms |
| GET /v1/entity/product/{id} | 5 | 0 | 0.00% | 5.03 | 110.0 ms | 130.0 ms | 130.0 ms |
| GET /v1/entity/user/{id} | 3 | 0 | 0.00% | 3.02 | 30.0 ms | 140.0 ms | 140.0 ms |
| GET /v1/metrics/{name} | 9 | 0 | 0.00% | 9.05 | 18.0 ms | 150.0 ms | 150.0 ms |
| POST /v1/query | 5 | 0 | 0.00% | 5.03 | 29.0 ms | 160.0 ms | 160.0 ms |

## Release Gate Context

- README no longer carries a benchmark claim table, so this run is compared against the release gate instead of documentation copy.
- Measured aggregate: p50 28.0 ms, p99 160.0 ms.
- Release gate for `/v1/entity/*`: p50 < 100 ms and p99 < 500 ms.
- Slowest entity endpoint in this run: `GET /v1/entity/user/{id}` at p50 30.0 ms, p99 140.0 ms.
- Aggregate throughput was 25.13 RPS with `50` concurrent users.

## Notes

- This report is generated from a fresh DuckDB dataset on every run.
- Re-running `python scripts/run_benchmark.py` overwrites this file with new measurements.
