# Real-path throughput benchmark artifact lifecycle

`python scripts/benchmark_throughput_realpath.py` owns the Kafka → Flink →
serving bridge → ClickHouse throughput measurement family. The default command
writes both mutable outputs under the ignored runtime artifact directory:

- `.artifacts/throughput/realpath-current.md` — human-readable report;
- `.artifacts/throughput/realpath-current.json` — machine-readable results.

Re-running the command replaces those runtime files. The script refuses to
write either this lifecycle page or the archived baseline, so a benchmark run
cannot silently mutate tracked documentation.

## Tracked evidence

The former pre-Q1.2 report stored at this path is preserved as the immutable
[2026-07-09 S10 burst baseline](../archive/performance/throughput-realpath-2026-07-09.md):
400 events, 699 events/s produce, 7.97 events/s bridge apply, zero duplicates
and apply failures, with lag returning to zero on the measured Mac/Colima
stand.

Later date-stamped records remain separate evidence identities. The
[Q1.2 re-measure](throughput-realpath-q12-2026-07-09.md) begins the narrow
Q1.2 → Q1.3 → Q1.4 optimization chain, while the
[four-hour paced r4 PASS](throughput-realpath-paced100-4h-r4-2026-07-19.md)
owns the closed pre-materializer serving-path endurance result. These modes do
not form one direct supersession chain and do not establish a production SLA
or production acceptance.

Real-path throughput measurements require Kafka, Flink, the serving bridge,
ClickHouse, and host-specific runtime state. Run that infrastructure on
`deproject-mac`, not the Windows development host. Measurements have no
byte-for-byte regeneration check; promote a meaningful run only under a
date-stamped filename with its JSON companion and exact run, host, source, and
configuration provenance.
