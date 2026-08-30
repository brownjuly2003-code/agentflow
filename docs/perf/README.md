# Performance evidence

This directory holds current and historical performance evidence. The
[full-load benchmark lifecycle](load-benchmark-latest.md) names the ignored
runtime outputs and promotion rule; the former mutable report is preserved as
an [archived 2026-04-17 snapshot](../archive/performance/load-benchmark-2026-04-17.md).
Targeted entity-latency snapshots and flamegraphs remain alongside it. The
[demo freshness benchmark lifecycle](freshness-benchmark.md) names separate
ignored runtime outputs; its former mutable report is preserved as an
[archived 2026-06-06 snapshot](../archive/performance/freshness-benchmark-2026-06-06.md).
The [S8 real-path freshness lifecycle](freshness-e2e-realpath.md) keeps its
Mac runtime outputs ignored; the measured full-path result is preserved as an
[archived 2026-07-09 snapshot](../archive/performance/freshness-e2e-realpath-2026-07-09.md).
The [real-path throughput benchmark lifecycle](throughput-realpath.md) keeps
Mac runtime outputs ignored; its pre-Q1.2 S10 burst baseline is preserved as
an [archived 2026-07-09 snapshot](../archive/performance/throughput-realpath-2026-07-09.md).
Non-canonical mixed-load reports from the former `docs/benchmark_pool*.md`
series are preserved in the [documentation archive](../archive/performance/README.md).

## Tooling

- `scripts/profile_entity.py` — client-side latency harness. Hits one
  entity endpoint `N` times at fixed concurrency and prints a JSON
  summary with `p50_ms`, `p95_ms`, `p99_ms`, throughput, and raw counts.
  This is the cheapest way to check "did my change move the needle"
  without spinning up the full Locust matrix.
- `scripts/run_benchmark.py` — full Locust matrix across the whole API
  surface. Slower to start; writes `.artifacts/benchmark/benchmark.md` and
  `.artifacts/benchmark/current.json` rather than a mutable tracked report.
- `scripts/benchmark_freshness.py` — in-process demo event-to-metric freshness
  harness. Writes `.artifacts/freshness/freshness-benchmark.md` and
  `.artifacts/freshness/current.json`; the tracked path is its lifecycle page.
- `scripts/benchmark_freshness_e2e.py` — Kafka → Flink → bridge → ClickHouse →
  Redis → API event-to-metric freshness harness for the Mac runtime stand.
  Writes `.artifacts/freshness/e2e-realpath.md` and
  `.artifacts/freshness/e2e-realpath-current.json`; the tracked undated path is
  its lifecycle page.
- `scripts/benchmark_throughput_realpath.py` — Kafka → Flink → bridge →
  ClickHouse harness for the Mac runtime stand. Writes
  `.artifacts/throughput/realpath-current.md` and
  `.artifacts/throughput/realpath-current.json`; the tracked undated path is
  its lifecycle page.
- `py-spy` — external sampling profiler. Attach to the live uvicorn
  process (no restart required) and record a flamegraph.
- `.github/perf-history.json` + `make perf-plot` — rolling trend of
  the aggregate load-test metrics. Useful for spotting slow drifts.

## Stack requirements for meaningful numbers

Attempting to measure `/v1/entity/{type}/{id}` against a bare uvicorn
without the supporting services produces misleading numbers:

- `/v1/health` fans out to Kafka via `rdkafka` and blocks for ~10 s
  while retrying the missing broker. A health probe issued concurrently
  with a load run stalls the event loop.
- `QueryCache` logs one warning per `get`/`set` when Redis is
  unreachable, i.e. two synchronous stderr writes per request. At
  concurrency 16 this alone can dominate the latency budget.
- The auth middleware logs each request through the usage DB
  (`agentflow_api.duckdb`), which is single-writer.

Before benchmarking, bring up the full compose stack:

```bash
docker compose up -d redis kafka
make demo
```

When running inside Docker is not possible, set `REDIS_URL` to a
reachable redis instance anyway (even a port-forwarded one) so the
cache stays on its happy path. Do not benchmark an API that is still
emitting `query_cache_unavailable` warnings — you are measuring
logging, not the serving path.

## Recommended workflow for a hypothesis

1. Start the API in a clean terminal: `make demo` (or equivalent). Note
   the uvicorn PID.
2. Capture a baseline:
   ```bash
   python scripts/profile_entity.py \
     --host http://localhost:8000 \
     --entity-type order \
     --entity-id ORD-20260401-7829 \
     --iterations 2000 \
     --concurrency 16 \
     --output docs/perf/entity-latency-before.json
   ```
3. Start a flamegraph sampler in parallel:
   ```bash
   py-spy record --pid <uvicorn-pid> --duration 30 --output docs/perf/flamegraph-before.svg
   ```
4. Drive the same load against the API while `py-spy record` is active
   (re-run step 2 without `--output` is fine).
5. Apply the code change. Restart `make demo`.
6. Repeat steps 2 and 3 with `-after` suffixes.
7. Compare the two `entity-latency-*.json` files; if p99 improved by
   less than 5%, drop the change per the T05 ground rule.

## File naming

- `entity-latency-<label>.json` — harness output for one run.
- `flamegraph-<label>.svg` — py-spy flamegraph for one run.
- `entity-profile-<label>.md` — written by hand, summarizes the top 20
  functions from the flamegraph plus the hypothesis being evaluated.

`label` is usually `before`, `after`, or a hypothesis slug like
`sqlglot-cache`.

## Ground rules

- Compare runs on the same hardware, with the demo stack in the same
  state, back-to-back. Numbers across different machines do not mean
  anything.
- Warm up the API before the measured window (the harness does 20
  warmup hits by default).
- If a hypothesis does not beat the 5% threshold, do not commit it —
  park the branch and move to the next hypothesis.
