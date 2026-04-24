# Entity Latency Profile — After PII Masker Cache Fix

**Date:** 2026-04-24
**HEAD:** `220f94c`
**Baseline compared:** `entity-latency-baseline-2026-04-24.json` (HEAD `97a1902`)
**Change under test:** `perf(api): normalize PII masker cache key via pathlib.Path` (220f94c)

## Summary

| Metric | Baseline | After fix | Delta |
|---|---|---|---|
| p50 | 179.29 ms | 56.65 ms | **−68%** |
| p95 | 615.62 ms | 233.78 ms | **−62%** |
| p99 | 936.34 ms | 360.97 ms | **−61%** |
| throughput | 68.57 RPS | 193.73 RPS | **+183%** |
| wall time (2000 req) | 29.17 s | 10.32 s | −65% |

All 2000 requests succeeded, zero failures. Same machine, same stack config, same fixture row (`ORD-20260404-1001`), same parameters (iterations=2000, concurrency=16, warmup=20).

## Why the win is larger than Codex predicted

`entity-profile-2026-04-24.md` estimated a 10–15 % p99 reduction (~90–140 ms) based on the flamegraph share of `_get_pii_masker()` + `PiiMasker.__init__` (~35 % CPU). The observed delta is **−61 %** (~575 ms). Two likely reasons the flamegraph underestimated the cost:

1. **Event-loop blocking.** `PiiMasker.__init__` calls synchronous YAML parsing and file I/O. Under concurrency=16, even a 35 % CPU-share frame serialises the async event loop — latency impact scales super-linearly with concurrency, not linearly with CPU time.
2. **Amortised import graph warm-up.** Each rebuild re-imported modules during constructor work, triggering Python import-lock contention between workers; this does not render prominently in a CPU flamegraph but shows up in wall-clock latency.

Both are side effects of the cache key mismatch, not separate hypotheses.

## Implications

- **CI smoke gate (A03 split-decision, p99 < 500 ms target):** now passes on this hardware — 361 ms p99 with headroom.
- **Nightly SLO (p99 < 200 ms):** still ~1.8× over target. Next candidate hot frames should be re-profiled from a fresh flamegraph; `entity-profile-2026-04-24.md` secondary frames (DuckDB pool contention, orjson cost share) are likely to shift after the PII masker is out of the hot path.
- **Load Test (`tests/load/thresholds.py`):** thresholds were set to 50 ms p95 on entity — still unreachable even after this win. Any threshold-touch work should wait until the nightly benchmark stabilises under the A03 contract and we have CI-runner numbers rather than local-dev numbers.

## Reproducibility

- Redis: `de_project-redis-1` up & healthy
- DuckDB: `agentflow_demo.duckdb` seeded from a prior `python -m src.processing.local_pipeline --burst 500` run
- API: `.venv/Scripts/python.exe -m uvicorn src.serving.api.main:app --host 127.0.0.1 --port 8000`
- Harness: `python scripts/profile_entity.py --iterations 2000 --concurrency 16 --entity-type order --entity-id ORD-20260404-1001 --output docs/perf/entity-latency-after-pii-masker-cache.json`
- No concurrent `/v1/health` probes during the measured window. (One probe used pre-warmup to confirm API was live; harness was started 12 s after the probe to let the rdkafka retry window expire.)

## Next

1. Capture a fresh flamegraph under the new hot path — `py-spy record -o docs/perf/flamegraph-after-pii-masker-cache.svg` while `profile_entity.py` runs.
2. Update `entity-profile-2026-04-24.md` backlog: drop (1) PII masker (closed); re-evaluate ordering of DuckDB pool, orjson, and usage-DB single-writer contention based on the new flamegraph.
3. Do NOT touch `tests/load/thresholds.py` yet — see Implications.
