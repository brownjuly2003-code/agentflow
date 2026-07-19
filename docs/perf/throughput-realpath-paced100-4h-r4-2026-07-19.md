# S10 paced produce @ 100 eps — 4-hour soak, run r4 (PASS)

> Measured: `2026-07-19T06:34Z` → `10:34Z` on `deproject-mac`
> (Colima vz 6 GiB / 4 CPU / 60 GiB docker volume, fresh VM, log-rotation 50m×3,
> `KAFKA_BROKER_SESSION_TIMEOUT_MS=45000`, delivery-guarded bench). Code: `main`
> @ `9ae4429` (soak stack; the later security merges don't touch this path).
> Path: Kafka → Flink stream_processor (**1 TM**) → `events.validated` → host
> `bridge_consumer` → ClickHouse. JSON: `/tmp/s10_soak4h_r4.json` on the stand.

## Result — PASS

| Metric | Value | Gate | |
|--------|------:|------|:--:|
| Produce | **100.0 eps** (1 440 000 events in 14 400.0 s, paced) | ≥ 95 | ✓ |
| Flink hop | **99.9 eps** (1 440 000 validated) | ≥ 90 | ✓ |
| Bridge apply | **99.9 eps** (+1 440 000 unique applied) | ≥ 90 | ✓ |
| Apply failures | **0** | = 0 | ✓ |
| Duplicates | **0** | < 5 000 | ✓ |
| Lag start → end | 0 → **0** (peak 1956) | end ≤ 100 | ✓ |

`consumed = applied = 1 440 000` exactly. Flink job **never restarted**
(`checkpoints: restored 0, completed 484/484, failed 0`); disk stayed ≤ 74 %
for the full window. **Multi-hour sustained ≥100 eps through the real
Kafka→Flink→bridge→ClickHouse path is now proven end-to-end, exactly once.**

## Why this run passed where r1 and r3 did not

Both prior 4 h attempts failed for reasons outside the apply path, and each
motivated one fix; r4 is the first run with all of them in place:

1. **r1 (2026-07-18) — stand disk exhaustion.** The docker volume entered ~50 GiB
   full and TM/JM logs (json-file, no rotation) pushed it to 100 %, MinIO
   checkpoints failed, the job crash-looped (116 restarts, 292 k replays) and TM
   died on a full disk. → Fresh VM + prune + **json-file log rotation (50m×3)**.
   r4 disk peaked at 74 %.
2. **r3 (2026-07-19 early) — harness lost produce after a broker self-fence.**
   The single-node KRaft broker fenced itself for 16 s under host load; the
   fire-and-forget bench producer (no delivery callback) then silently expired
   408 k messages while counting them as produced. → **Broker session timeout
   9 s → 45 s** + **bench delivery guard** (on_delivery hook, fail-fast, checked
   flush). r4 saw no fencing blips and `produced == delivered == 1 440 000`.

The apply path itself was never the problem — r1 proved exact dedup under a
292 k replay storm, r3 proved 100 % of *delivered* events applied exactly. r4
now closes the loop: 100 % of *produced* events, exactly once, over 4 hours.

## Reproduce

Fresh Colima VM (`GODEBUG=netdns=cgo colima start`, log-rotation in colima.yaml),
`docker compose -f docker-compose.yml -f docker-compose.flink.yml up -d
--scale flink-taskmanager=1 flink-job-runner clickhouse redis` (bring MinIO up
first if healthchecks are slow, and `docker rm -f` a wedged kafka-init after a
VM restart), start `bridge_consumer` and wait for `:9108`, then
`scripts/benchmark_throughput_realpath.py --count 1440000 --pace-eps 100
--catchup-timeout-seconds 2400`. Pre-flight: disk ≤ 80 %, no other heavy work
on the host.

## Status

**4 h paced @ 100 eps: PASS.** The multi-hour soak gate is closed.
