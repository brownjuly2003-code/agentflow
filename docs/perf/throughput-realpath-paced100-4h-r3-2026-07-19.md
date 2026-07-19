# S10 paced produce @ 100 eps — 4-hour soak, run r3 (FAIL: harness silently lost produce)

> Measured: `2026-07-19T01:26Z` → `06:07Z` on `deproject-mac`
> (Colima vz 6 GiB / 4 CPU / 60 GiB docker volume, fresh VM restart, log-rotation
> 50m×3 active). Code: `main` @ `05afb32`. Path: Kafka → Flink stream_processor
> (**1 TM**) → `events.validated` → host `bridge_consumer` → ClickHouse.
> JSON: `/tmp/s10_soak4h_r3.json`; logs `/tmp/r3_jm.log`, `/tmp/r3_tm.log` on the stand.

## Result

| Metric | Value |
|--------|------:|
| Produce (as counted by bench) | **100.0 eps** paced, 1 440 000 in 14 430 s |
| Produce (actually delivered to Kafka) | **1 031 462** — 408 538 lost client-side |
| Flink hop | 1 031 462 validated = **100 % of delivered** |
| Bridge apply | +1 031 462 unique = **100 % of validated** |
| Failures / duplicates | **0 / 0** |
| Lag start → end | 0 → **0** (peak 2015) |
| Flink restarts / checkpoints | **0 restarts**, 578/578 checkpoints COMPLETED |

**Gate:** produce ✓ / flink 61.3 ✗ / apply 61.3 ✗ → formally **FAIL**, but the
shortfall is entirely upstream of the product: the pipeline processed every
event that reached Kafka, exactly once, with zero failures over 4.7 h.
**Multi-hour sustained ≥100 eps remains open** — the path only saw real load
for 2 h 52 m.

## Root cause — two stacked defects, neither in the serving path

**1. Stand: single-node KRaft broker fenced itself for 16 seconds.**
Broker and controller share one JVM yet heartbeat over TCP. From 04:15:29Z
heartbeats timed out (4 500 ms limit) under host load; at **04:18:13Z** the
controller fenced the broker (`Fencing broker 1 because its session has timed
out`), all **84 partitions went leaderless**; at **04:18:29Z** it unfenced and
leaders were restored. Total outage: **16 s**. Identical blips recurred at
06:04 and 06:13 — this is chronic on a 4-core VM, not a one-off.

**2. Harness: fire-and-forget producer wedged permanently and lied about it.**
The bench produced with no `on_delivery` callback and an unchecked `flush(30)`.
confluent-kafka 2.15.0 (librdkafka 2.15.0) received the leaderless metadata
during the 16 s window (`new leader-1 not found in cache`, 04:18:56Z) and
**never re-resolved the leaders** — although a fresh producer on the same host
port produced fine (verified live post-run, delivery err=None). From 04:18:56Z
to the end every queued message silently expired after `message.timeout.ms`
(300 s): steady-state queue depth ≈ 300 s × 100 eps = 30 000 stayed below the
100 k buffer, so `produce()` never raised and the pace loop counted phantom
events to 1 440 000. At termination librdkafka reported
`26 983 messages still in queue or transit` — the un-expired tail
(≈ 270 s × 100 eps), unchecked. Net client-side loss: **408 538 events**.

Evidence chain: broker log (fence 04:18:13 → unfence 04:18:29); bench log
(rdkafka METADATAUPDATE burst 04:18:56, then silence until TERMINATE);
`orders.raw` end-offsets sum **exactly 1 031 462** with Flink group lag 0 on
all six partitions; `events.validated` end-offsets sum exactly the same.

## What r3 proved anyway

- The full streaming path ran **4.7 h with zero loss, zero duplicates, zero
  failures** on everything actually delivered (consumed = applied exactly).
- Flink rode out multiple broker fencing blips with **no job restarts** and a
  perfect checkpoint record (578/578, ~30 s cadence, sub-second latency).
- Fresh-VM + log-rotation remediation from r1 held: disk peaked at 73 %.

## Remediation (implemented in the same change that adds this report)

1. **Bench fails fast and loud**: every `produce()` carries an `on_delivery`
   hook; the paced loop aborts (exit 3) on the first surfaced delivery failure;
   the final `flush(120)` must drain clean or the run aborts. A 16 s broker
   blip that librdkafka rides out (retries within 300 s) does NOT abort; only
   genuinely lost events do.
2. **Broker session timeout 9 s → 45 s** (`KAFKA_BROKER_SESSION_TIMEOUT_MS`,
   base compose): self-fencing now requires a 45 s host stall.

## Run-r2 (context, still undiagnosed)

r2's TM death (exit=1, 10 min in) remains unexplained — its logs were lost.
r3 adds evidence that this stand chronically degrades under host contention
(repeated broker self-fencing), which is consistent with a stand-level cause
for r2 but does not prove it.

## Next

r4 with guarded bench + hardened broker on a fresh stack (`down -v`).
