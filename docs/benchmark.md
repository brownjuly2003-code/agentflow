# AgentFlow Benchmark Report

> This file is overwritten by the latest long-running benchmark. For entity-specific optimization evidence, see `docs/perf/entity-benchmark-contract.md`.

Generated: `2026-04-17T12:55:58+03:00`

## System Under Test

- OS: `Windows-11-10.0.26200-SP0`
- CPU: `Intel64 Family 6 Model 170 Stepping 4, GenuineIntel` (18 logical cores)
- RAM: `15.5 GB`
- Python: `3.13.7`

## Test Parameters

- Host: `http://127.0.0.1:8001`
- Seed step: `python -m src.processing.local_pipeline --burst 500`
- Load profile: `20` users, spawn rate `10/s`, duration `30s`
- Locust file: `tests/load/locustfile.py`

## Results

| Endpoint | Requests | Failures | Failure Rate | RPS | p50 | p95 | p99 |
|----------|----------|----------|--------------|-----|-----|-----|-----|
| ALL | 25 | 0 | 0.00% | 20.85 | 140.0 ms | 430.0 ms | 460.0 ms |
| POST /v1/batch | 2 | 0 | 0.00% | 1.67 | 430.0 ms | 430.0 ms | 430.0 ms |
| GET /v1/entity/order/{id} | 1 | 0 | 0.00% | 0.83 | 300.0 ms | 300.0 ms | 300.0 ms |
| GET /v1/entity/product/{id} | 2 | 0 | 0.00% | 1.67 | 210.0 ms | 210.0 ms | 210.0 ms |
| GET /v1/entity/user/{id} | 3 | 0 | 0.00% | 2.50 | 380.0 ms | 460.0 ms | 460.0 ms |
| GET /v1/metrics/{name} | 12 | 0 | 0.00% | 10.01 | 130.0 ms | 180.0 ms | 180.0 ms |
| POST /v1/query | 5 | 0 | 0.00% | 4.17 | 82.0 ms | 180.0 ms | 180.0 ms |

## Release Gate Context

- README no longer carries a benchmark claim table, so this run is compared against the release gate instead of documentation copy.
- Measured aggregate: p50 140.0 ms, p99 460.0 ms.
- Release gate for `/v1/entity/*`: p50 < 100 ms and p99 < 500 ms.
- Slowest entity endpoint in this run: `GET /v1/entity/user/{id}` at p50 380.0 ms, p99 460.0 ms.
- Aggregate throughput was 20.85 RPS with `20` concurrent users.

## Notes

- This report is generated from a fresh DuckDB dataset on every run.
- Re-running `python scripts/run_benchmark.py` overwrites this file with new measurements.
