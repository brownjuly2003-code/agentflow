# Full-load benchmark artifact lifecycle

`python scripts/run_benchmark.py` owns the full-API Locust measurement family.
The default command writes both mutable outputs under the ignored runtime
artifact directory:

- `.artifacts/benchmark/benchmark.md` — human-readable report;
- `.artifacts/benchmark/current.json` — machine-readable results consumed by
  the performance comparison gate.

Re-running the command replaces those runtime files. The script refuses to
write either this lifecycle page or an archived snapshot, so a benchmark run
cannot silently mutate tracked documentation.

## Tracked evidence

The last report formerly stored at this path is preserved as the immutable
[2026-04-17 historical snapshot](../archive/performance/load-benchmark-2026-04-17.md).
It records a local 20-user, 30-second run and is not the current release gate.

Full-load measurements depend on the host, timestamp, service state, and live
request sample, so they have no byte-for-byte regeneration check. CI generates
fresh ignored artifacts and compares their JSON metrics with
`docs/benchmark-baseline.json`. Promote a release-worthy measurement into
`docs/perf/` only with a date-stamped filename, its JSON companion, and exact
run/host/source provenance; never recreate a mutable tracked "latest" report.

For the repeatable entity-only procedure and its comparability rules, use the
[entity latency benchmark contract](entity-benchmark-contract.md).
