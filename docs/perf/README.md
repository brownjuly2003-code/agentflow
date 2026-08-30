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
The [authentication legacy-path benchmark lifecycle](auth-bench.md) owns an
ignored runtime report while preserving the dated 2026-05-26 bcrypt evidence.
Local performance-history tooling also writes only ignored runtime artifacts;
the retired bot-managed log is preserved as an
[archived 2026-04-27 snapshot](../archive/performance/perf-history-2026-04-27.json).
Non-canonical mixed-load reports from the former `docs/benchmark_pool*.md`
series are preserved in the [documentation archive](../archive/performance/README.md).
Entity quick-profile runs also stay outside this directory by default:
`scripts/profile_entity.py` owns ignored
`.artifacts/perf-smoke/entity-profile.json`; the tracked entity JSON, SVG, and
write-ups here are point-in-time evidence, not mutable runtime destinations.
NL-to-SQL evaluation runs likewise write ignored
`.artifacts/nl-sql-eval/current.md`; the two dated 2026-07-01 records remain
immutable direct-translator evidence, not mutable destinations or production
accuracy claims.

## Tooling

- `scripts/profile_entity.py` — client-side latency harness. Hits one
  entity endpoint `N` times at fixed concurrency and prints a JSON
  summary with `p50_ms`, `p95_ms`, `p99_ms`, throughput, and raw counts. It
  writes `.artifacts/perf-smoke/entity-profile.json` by default, resolves
  relative output paths from the project root, and refuses output under
  `docs/perf/`. This is the cheapest way to check "did my change move the
  needle" without spinning up the full Locust matrix.
- `scripts/run_benchmark.py` — full Locust matrix across the whole API
  surface. Slower to start; writes `.artifacts/benchmark/benchmark.md` and
  `.artifacts/benchmark/current.json` rather than a mutable tracked report.
- `tests/load/run_load_test.py` — Locust p99 CI-smoke runner owned by
  `python tests/load/run_load_test.py`. Writes `.artifacts/load/results` (CSV
  prefix) and `.artifacts/load/results.json` by default, resolves relative
  output paths from the project root, and refuses destinations under
  `docs/perf/` or `tests/load/`. Compare a run with
  `python scripts/check_performance.py --baseline docs/benchmark-baseline.json
  --current .artifacts/load/results.json`. This is host/time-dependent CI-smoke
  runtime evidence, not a byte-regenerated tracked reference, production SLA,
  full-load benchmark, or acceptance.
- `scripts/benchmark_freshness.py` — in-process demo event-to-metric freshness
  harness. Writes `.artifacts/freshness/freshness-benchmark.md` and
  `.artifacts/freshness/current.json`; the tracked path is its lifecycle page.
- `scripts/benchmark_freshness_realpath.py` — Kafka → Flink →
  `events.validated` streaming-hop freshness harness for the Mac runtime stand.
  Writes `.artifacts/freshness/realpath-current.json` and refuses to overwrite
  the immutable 2026-06-30 evidence record; reviewed runs require a new dated
  identity with complete provenance.
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
- `scripts/benchmark_scale_own_data.py` — own synthetic-data scale and
  correctness harness against live ClickHouse on the Mac stand. Writes
  `.artifacts/scale/own-data-current.md` and
  `.artifacts/scale/own-data-current.json`, protects the immutable S13 record,
  and requires a new dated identity to promote a reviewed run.
- `scripts/perf/auth_bench.py` — explicit legacy bcrypt O(n) authentication
  reproduction plus current rate-window trim microbenchmark. Run the
  host-dependent workload on the Mac; it writes
  `.artifacts/perf/auth-bench-current.md`, protects both tracked auth benchmark
  pages, and does not represent the current O(1) authentication path.
- `scripts/run_nl_sql_eval.py` — direct-translator execution-accuracy harness
  on the fixed in-memory DuckDB demo set. Writes
  `.artifacts/nl-sql-eval/current.md`, resolves relative output paths from the
  project root, and rejects output under `docs/perf/` before evaluation. The
  rule-based default is reproducible locally; the opt-in LLM path is live and
  non-deterministic. Promote either only under a new date-stamped identity with
  source, host/runtime, engine/model, exact command/configuration, and report
  hash provenance.
- `py-spy` — external sampling profiler. Attach to the live uvicorn
  process (no restart required) and record a flamegraph.
- `scripts/record_perf_history.py` + `scripts/plot_perf_history.py` — append
  aggregate load-test metrics to `.artifacts/perf-history/history.json` and
  render ignored `history.html` plus optional `history.png`. Useful for
  comparing repeated runs in one checkout.

## Performance history artifact lifecycle

`python scripts/record_perf_history.py --results <results.json>` owns the local
rolling JSON. Relative paths resolve from the project root, and the recorder
refuses to overwrite either the former `.github/perf-history.json` path or its
immutable archived snapshot. `python scripts/plot_perf_history.py` reads that
runtime JSON and writes under `.artifacts/perf-history/` by default; it refuses
plot output anywhere under `docs/`.

The original workflow appended four main-branch results through 2026-04-27.
Its bot commit required `contents: write`, but branch protection rejected the
self-push before the required checks could be satisfied, so commit `b2c0bc0`
removed the writer. The exact four-entry JSON remains in the
[dated archive](../archive/performance/perf-history-2026-04-27.json).

Current CI uploads each run's benchmark results but does not persist a
cross-run history. Therefore the ignored local history and its plots are
diagnostic runtime artifacts, not a continuous CI trend, release evidence,
an SLA, or production acceptance.

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
     --output .artifacts/perf-smoke/entity-latency-before.json
   ```
3. Start a flamegraph sampler in parallel:
   ```bash
   py-spy record --pid <uvicorn-pid> --duration 30 --output .artifacts/perf-smoke/flamegraph-before.svg
   ```
4. Drive the same load against the API while `py-spy record` is active
   (re-run step 2 without `--output` is fine).
5. Apply the code change. Restart `make demo`.
6. Repeat steps 2 and 3 with `-after` suffixes.
7. Compare the two `.artifacts/perf-smoke/entity-latency-*.json` files; if p99 improved by
   less than 5%, drop the change per the T05 ground rule.

## File naming

- `.artifacts/perf-smoke/entity-latency-<label>.json` — runtime harness output.
- `.artifacts/perf-smoke/flamegraph-<label>.svg` — runtime py-spy flamegraph.
- `entity-profile-<label>.md` — written by hand, summarizes the top 20
  functions from the flamegraph plus the hypothesis being evaluated.

`label` is usually `before`, `after`, or a hypothesis slug like
`sqlglot-cache`.

Promote a result only after review, under a new date-stamped `docs/perf/`
identity with host/runtime details, source SHA, exact command, sample counts,
and its profile write-up. The harness will not overwrite tracked evidence.

## Ground rules

- Compare runs on the same hardware, with the demo stack in the same
  state, back-to-back. Numbers across different machines do not mean
  anything.
- Warm up the API before the measured window (the harness does 20
  warmup hits by default).
- If a hypothesis does not beat the 5% threshold, do not commit it —
  park the branch and move to the next hypothesis.
