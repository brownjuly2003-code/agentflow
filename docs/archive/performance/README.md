# Archived performance reports

This directory preserves non-canonical mixed-load runs and superseded
performance narratives that previously lived in the `docs/` root. Historical
measurements remain intact, but they are not the current performance gate.

## Mixed-load benchmark reports

| Archived report | Original path | Generated | Measurement profile |
| --- | --- | --- | --- |
| [`benchmark_pool16.md`](benchmark_pool16.md) | *docs/benchmark_pool16.md* | 2026-04-17 07:55 +03:00 | 50 users / 20 s |
| [`benchmark_pool16_60s.md`](benchmark_pool16_60s.md) | *docs/benchmark_pool16_60s.md* | 2026-04-17 07:58 +03:00 | 50 users / 60 s |
| [`benchmark_pool24_60s.md`](benchmark_pool24_60s.md) | *docs/benchmark_pool24_60s.md* | 2026-04-17 07:59 +03:00 | 50 users / 60 s, different pool configuration |
| [`freshness-benchmark-2026-06-06.md`](freshness-benchmark-2026-06-06.md) | *docs/perf/freshness-benchmark.md* | 2026-06-06 10:10 +03:00 | In-process DuckDB demo shortcut; former mutable tracked report |
| [`freshness-e2e-realpath-2026-07-09.md`](freshness-e2e-realpath-2026-07-09.md) | *docs/perf/freshness-e2e-realpath.md* | 2026-07-09 15:33 UTC | S8 event-to-live-metric real path; former mutable tracked report |
| [`load-benchmark-2026-04-17.md`](load-benchmark-2026-04-17.md) | *docs/perf/load-benchmark-latest.md* | 2026-04-17 12:55 +03:00 | 20 users / 30 s; former mutable tracked report |
| [`throughput-realpath-2026-07-09.md`](throughput-realpath-2026-07-09.md) | *docs/perf/throughput-realpath.md* | 2026-07-09 15:41 UTC | Pre-Q1.2 S10 real-path burst baseline; former mutable tracked report |

The mixed-load parameters differ, so the reports must not be combined into a
trend.

## Retired generated histories

| Archived snapshot | Original path | Last entry | Lifecycle |
| --- | --- | --- | --- |
| [`perf-history-2026-04-27.json`](perf-history-2026-04-27.json) | *.github/perf-history.json* | 2026-04-27 08:14 UTC | Exact four-entry bot-managed log. The writer was removed after branch protection rejected its self-push; current history is ignored local runtime state. |

The snapshot was archived on 2026-08-30 without changing its tracked Git blob
`8ba12095aa0aefe43cff2cb78ecb9cbbb22edb65`; its SHA-256 is
`3b522ea0e68159a3147538ec124bcec73fcebf06a762d9537db9b11aa37b9573`.

## Superseded follow-ups

| Archived report | Original path | Recorded | Current replacement |
| --- | --- | --- | --- |
| [`regression-report.md`](regression-report.md) | *docs/regression-report.md* | 2026-04-17 | [Entity benchmark contract](../../perf/entity-benchmark-contract.md) and [2026-04-24 entity profile](../../perf/entity-profile-2026-04-24.md) |

Use the [full-load benchmark artifact lifecycle](../../perf/load-benchmark-latest.md),
the [demo freshness benchmark lifecycle](../../perf/freshness-benchmark.md),
the [S8 real-path freshness lifecycle](../../perf/freshness-e2e-realpath.md),
and the [real-path throughput benchmark lifecycle](../../perf/throughput-realpath.md)
for current output and promotion rules. New mutable reports belong under
their ignored `.artifacts/` directories; use the
[entity benchmark contract](../../perf/entity-benchmark-contract.md) for
repeatable entity-latency comparisons and the
[performance evidence hub](../../perf/README.md) for the current local-history
lifecycle.

Return to the [archive map](../README.md) or the
[documentation hub](../../README.md).
