# S10 paced produce @ 100 eps — 4-hour soak attempt (FAIL, stand disk exhaustion)

> Measured: `2026-07-18T00:23:20Z` → `05:03:25Z` on `deproject-mac`
> (Colima vz 6 GiB / 4 CPU / 60 GiB docker volume). Code: `main` @ `05afb32`.
> Path: Kafka → Flink stream_processor (**1 TM**) → `events.validated` →
> host `bridge_consumer` → ClickHouse.
> JSON: `/tmp/s10_soak4h.json` on the stand.

## Result

| Metric | Value |
|--------|------:|
| Produce | **100.0 eps** (1 440 000 events in 14 400.0 s, paced) |
| Flink hop | **84.8 eps** (1 424 309 validated msgs, incl. replays) |
| Bridge apply | **67.4 eps** (+1 132 164 unique applied over 16 800 s incl. catch-up timeout) |
| Failures / duplicates | **0 / 292 145** |
| Lag start → end | 0 → **0** (peak 1939) |

**Gate:** produce ≥ 95 ✓, apply ≥ 90 ✗, flink ≥ 90 ✗, failures = 0 ✓,
duplicates < 5 000 ✗, lag_end ≤ 100 ✓ → **FAIL**.

## Root cause — stand infrastructure, not the apply path

The colima docker volume (59 GiB) entered the run ~50 GiB full
(37.85 GiB accumulated images ×55, ~8 GiB stale anonymous volumes,
3.4 GiB unrelated stacks). The soak's own footprint (~8 GiB: Kafka topic
data 1.5 GiB, CH 0.5 GiB, TM/JM container logs 3.8+1.7 GiB — json-file
driver, no rotation) filled it to 99–100 % by ~02:58Z.

Causal chain, all evidenced in JM/TM logs and `df`:

1. ~02:58Z first S3 upload retries from MinIO (same volume) on checkpoint
   `chk-315`; from 03:02Z checkpoint failures continuous.
2. CheckpointFailureManager fails the job → restart from last successful
   checkpoint → re-emission of already-validated events. 116 job restarts
   total; **292 145 duplicate deliveries** into `events.validated`.
3. 03:33:03Z the TM **container** dies (exit 127 on a full disk; no
   restart policy) → job stuck in `NoResourceAvailableException` forever;
   unique validated frozen at 1 132 164 (≈ events produced up to 03:33).
4. Bench finishes produce (produce lane unaffected: exactly 100.0 eps for
   4 h), waits out the 2 400 s catch-up timeout, reports FAIL.

Steady state before the disk filled was healthy for ~2.5 h:
at 01:30Z dup=0, lag ≤ 260; apply tracked produce ≈ 101 eps.

## What the failure proved anyway

- **Journal dedup held under a 292 k replay storm**: consumed = applied +
  duplicates exactly (1 424 309 = 1 132 164 + 292 145), apply_failures = 0.
  No event applied twice, no false failures.
- Produce pacing and the bridge stayed stable for the full window; the
  bridge drained its topic to lag 0 even while Flink crash-looped.

Not proved: multi-hour sustained ≥100 eps through Flink. The claim table
of the 1 h doc stands — **multi-hour remains open**.

## Stand remediation required before re-run

1. Free the docker volume: `docker image prune` (≈14.5 GiB reclaimable),
   remove stale anonymous volumes (≈8.7 GiB), keep unrelated stacks intact.
2. Cap container logs on the stand: colima `/etc/docker/daemon.json`
   `{"log-driver":"json-file","log-opts":{"max-size":"50m","max-file":"3"}}`
   (TM/JM wrote 5.5 GiB in one run; restart loops amplify this).
3. Pre-flight gate: **≥ 12 GiB free** on `/mnt/lima-colima` before starting
   a multi-hour arm (soak footprint ~8 GiB + margin).
4. Optional hardening exposed by this run: TM `restart: unless-stopped` in
   the compose flink overlay, so a container death degrades to a recoverable
   restart instead of a permanent stall.

## Reproduce

As in `throughput-realpath-paced100-1h-2026-07-17.md`, with
`--count 1440000 --pace-eps 100 --catchup-timeout-seconds 2400`, after the
pre-flight disk gate above.

## Status

**4 h paced @ 100 eps: FAIL — stand disk exhaustion at ~2.5 h** (checkpoint
storage + TM shared a 99 %-full docker volume). Apply-path integrity held
(0 failures, exact dedup of 292 k replays). Multi-hour gate remains open;
re-run after stand remediation.
