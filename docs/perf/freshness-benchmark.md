# Demo freshness benchmark artifact lifecycle

`python scripts/benchmark_freshness.py` owns the in-process DuckDB demo
event-to-metric measurement family. The default command writes both mutable
outputs under the ignored runtime artifact directory:

- `.artifacts/freshness/freshness-benchmark.md` — human-readable report;
- `.artifacts/freshness/current.json` — machine-readable results.

Re-running the command replaces those runtime files. The script refuses to
write either this lifecycle page or the archived snapshot, so a benchmark run
cannot silently mutate tracked documentation.

## Tracked evidence

The last report formerly stored at this path is preserved as the immutable
[2026-06-06 historical snapshot](../archive/performance/freshness-benchmark-2026-06-06.md).
It records the pre-S7 in-process demo shortcut on Windows with
fakeredis-backed cache semantics: 1.06 s p50 and 1.99 s p95 for the
`event_driven` arm. It does not measure Kafka, Flink, the serving bridge, or
ClickHouse and does not describe current production invalidation wiring.

The complementary [S8 real-path record](freshness-e2e-realpath.md) measures
Kafka through the live metric on the Mac/Colima stand. The two records cover
different execution scopes and are not a supersession chain.

Freshness measurements depend on the host, timestamp, and runtime state, so
they have no byte-for-byte regeneration check. Promote a release-worthy run
only under a date-stamped filename with its JSON companion and exact
run/host/source provenance; never recreate a mutable tracked latest report.
