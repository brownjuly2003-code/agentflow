# S8 real-path freshness artifact lifecycle

This page owns how to generate and promote the event-to-live-metric freshness
artifact. It does not contain current measurements and re-running the benchmark
must not overwrite tracked documentation.

The immutable 2026-07-09 S8 result is archived at
[`archive/performance/freshness-e2e-realpath-2026-07-09.md`](../archive/performance/freshness-e2e-realpath-2026-07-09.md).
That snapshot records 3.02 s p50 / 5.70 s p95 for 20 samples with one miss on
the single-node Mac/Colima Kafka → Flink → bridge → ClickHouse → Redis → API
path. It is not an SLA, a cross-host benchmark, or production acceptance.

## Owner and runtime outputs

Owning command: `python scripts/benchmark_freshness_e2e.py`.

Run the owning command on `deproject-mac` from an isolated checkout with the
required Kafka/Flink/bridge/ClickHouse/Redis/API stack:

```bash
python scripts/benchmark_freshness_e2e.py \
  --bootstrap 127.0.0.1:19092 --api-base http://127.0.0.1:8000 \
  --api-key <high-rpm-key> --iterations 20 --warmup 2
```

The command writes ignored, replaceable runtime artifacts:

- `.artifacts/freshness/e2e-realpath.md`
- `.artifacts/freshness/e2e-realpath-current.json`

Both output arguments are validated before Kafka, API, or other runtime access.
The current lifecycle page and archived snapshot are protected output targets.
Do not run Docker, WSL, kind, or equivalent infrastructure for this benchmark
on Windows.

## Promotion boundary

A runtime result becomes evidence only after review and promotion under a new
date-stamped path with exact source commit, host/runtime identity, full command,
configuration, sample/miss counts, JSON companion, and immutable hashes. Update
the evidence index and every numeric current-status claim in the same scoped
change. A fresh local run does not supersede the archived S8 record by itself.
