# Benchmark Split Decision

**Date:** 2026-04-24
**Context:** A03 entity latency re-baseline

## 1. Problem Statement

We currently have **one benchmark script** (`scripts/run_benchmark.py`) that tries to serve two incompatible purposes:

1. **CI smoke gate** -- fast feedback on PRs (should run in < 2 minutes).
2. **Release baseline** -- canonical evidence for SLO compliance and optimization tracking (needs minutes of stable load).

The old artifacts (`docs/benchmark.md`, `benchmark_pool16.md`, etc.) reflect this confusion: some runs use 20 users / 30 s, others 50 users / 60 s, producing p99 values that differ by 2-3x (160 ms vs 460 ms) on the same host. This made it impossible to agree on whether the `< 200 ms` target was met.

## 2. Decision

Split into **two distinct benchmarks** with separate thresholds.

### 2.1 Quick CI Perf Gate (Smoke / Regression Guard)

| Attribute | Value |
|-----------|-------|
| **Script** | `scripts/profile_entity.py` (entity-only) |
| **Trigger** | On every PR that touches `src/serving/**` |
| **Runtime** | < 60 seconds |
| **Load** | 2000 requests, concurrency 16 |
| **Purpose** | Catch major regressions (> 20 %) before merge. |
| **Threshold** | p99 **< 500 ms** (release gate, not SLO target) |
| **Artifact** | `docs/perf/ci-smoke-latest.json` (overwritten each run) |

**Why this threshold:**
- The current baseline is ~936 ms on the reference Windows stack.
- A 20 % regression from a fixed baseline would be flagged.
- Until the entity path is optimised to < 200 ms, the gate must not be stricter than the measured baseline + headroom.
- **This gate is NOT the optimization target; it is a safety rail.**

### 2.2 Long-Running Optimization Benchmark

| Attribute | Value |
|-----------|-------|
| **Script** | `scripts/run_benchmark.py` (full Locust matrix) |
| **Trigger** | Nightly CI + manually before release + after each merged perf PR |
| **Runtime** | ~5 minutes (seed + warmup + 60 s measured) |
| **Load** | 50 users, spawn rate 10/s, 60 s duration, mixed traffic |
| **Purpose** | Track progress toward the `< 200 ms` SLO; produce release-readiness evidence. |
| **Threshold** | p99 **< 200 ms** for entity endpoints (optimization target) |
| **Artifact** | `.artifacts/benchmark/<date>.json` + `docs/benchmark.md` (date-stamped, not overwritten) |

**Why 60 seconds minimum:**
- The 20 s and 30 s runs under-report tail latency because the warmup period dominates.
- The 60 s run is the first duration where p99 stabilised across repeated trials (see `benchmark_pool16_60s.md` vs shorter runs).
- Mixed traffic is realistic but dilutes entity-specific p99; therefore the **quick profile** remains the canonical source for entity-only changes.

## 3. Threshold Mapping

| Threshold | Value | Belongs to | Action if breached |
|-----------|-------|------------|-------------------|
| p99 < 500 ms | Release gate | Quick CI gate | Block PR merge; investigate regression. |
| p99 < 200 ms | SLO target | Long-running benchmark | Does **not** block release until formally adopted; tracks optimization backlog progress. |
| p50 < 100 ms | Soft goal | Long-running benchmark | Advisory only; entity endpoint currently ~180 ms p50. |

### 3.1 Current Thresholds

**Calibrated:** 2026-04-25 from GitHub Actions `Load Test` run
`24920594700` on `ubuntu-latest` at HEAD
`9953faaaa2198c416ce8a004df03f67db888ea60`, then widened on
2026-04-27 after run `24979982182` showed normal runner variance while
remaining below 1s on application endpoints.

The current mixed Locust CI smoke gate uses endpoint p99 thresholds from the
CI-runner baseline, rounded up with small headroom. The stricter `p99 < 500 ms`
entity gate remains the release target, but the measured runner baseline is
currently `600-700 ms` p99, so enforcing 500 ms here would keep main red without
identifying a new regression.

| Endpoint | CI baseline p95 | CI baseline p99 | Current CI gate |
|----------|----------------:|----------------:|----------------:|
| `GET /v1/entity/order/{id}` | 640 ms | 750 ms | p99 <= 750 ms |
| `GET /v1/entity/user/{id}` | 680 ms | 730 ms | p99 <= 750 ms |
| `GET /v1/entity/product/{id}` | 660 ms | 830 ms | p99 <= 900 ms |
| `GET /v1/metrics/{name}` | 650 ms | 770 ms | p99 <= 900 ms |
| `POST /v1/query` | 800 ms | 970 ms | p99 <= 1000 ms |
| `POST /v1/batch` | 790 ms | 940 ms | p99 <= 1000 ms |

`GET /v1/health` is intentionally excluded from load-test thresholds. The
10-run sample had cold-start dependency probes at p95/p99 `53000 ms`, which is
not a stable latency signal for the API endpoints under test.

## 4. File Lifecycle

| File | Purpose | Retention |
|------|---------|-----------|
| `docs/perf/entity-latency-baseline-*.json` | Canonical before/after for a perf PR | Permanent, linked from PR description |
| `docs/perf/flamegraph-*.svg` | Visual evidence for hot frames | Permanent |
| `docs/perf/ci-smoke-latest.json` | Latest CI smoke result | Overwritten each CI run |
| `.artifacts/benchmark/<date>.json` | Nightly/release long-run snapshot | Keep last 30 days in CI artifacts; promote to `docs/benchmark-<date>.md` for releases |
| `docs/benchmark.md` | Human-readable latest long-run report | Overwritten by `run_benchmark.py`; date-stamped copies for releases |
| `docs/benchmark_pool*.md` | **Historical drift artifacts** | Mark as `ARCHIVED` in header; do not use for comparison |

## 5. Recommended CI Changes

1. Add a GitHub Actions job `perf-smoke` that runs:
   ```bash
   docker compose up -d redis
   python -m src.processing.local_pipeline --burst 500
   python -c "from pathlib import Path; from scripts.run_benchmark import seed_benchmark_fixtures; seed_benchmark_fixtures(Path('agentflow_demo.duckdb'))"
   uvicorn src.serving.api.main:app --host 127.0.0.1 --port 8000 &
   python scripts/profile_entity.py --host http://localhost:8000 --entity-type order --entity-id ORD-20260404-1001 --iterations 2000 --concurrency 16 --output docs/perf/ci-smoke-latest.json
   ```
   Then assert `p99 < 500` via `jq`.

2. Add a scheduled nightly job `perf-baseline` that runs `python scripts/run_benchmark.py` with canonical parameters and uploads `.artifacts/benchmark/<date>.json` as an artifact.

3. Update `docs/benchmark.md` header to state:
   > "This file is overwritten by the latest long-running benchmark. For entity-specific optimization evidence, see `docs/perf/entity-benchmark-contract.md`."

## 6. Acceptance

- [x] `perf-smoke` CI job exists and fails if p99 > 500 ms.
- [x] `perf-baseline` nightly job exists and archives JSON artifacts.
- [x] Old `benchmark_pool*.md` files have an `ARCHIVED` header explaining they are historical input only.
- [ ] Team agrees that `< 200 ms` is the optimization target, not the merge gate.
