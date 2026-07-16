# S10 re-measure after Q1.4 (batched session/user read-modify-writes)

> Measured: `2026-07-10` on `deproject-mac` (Colima vz 6 GiB / 4 CPU, macOS 13.7.8 Intel)  
> Code: `main` @ `13a242d` (Q1.4 merged in #179)  
> Path: **ClickHouse only** — no DuckDB on the bridge  
> Machine-readable run record: `.artifacts/throughput/realpath-current.json` on the stand
> (its embedded timestamps read `~11:07Z`; the stand host clock runs ~10 h fast —
> the date in this filename is the real one).

## Results

| Arm | Pre-Q1.2 | Q1.2 | Q1.3 | **Q1.4** |
|-----|--------:|-----:|-----:|---------:|
| Produce rate | 699 eps | 217 eps | 647 eps | **376 eps** |
| Flink hop | 7.97 | 11.4 | 22.9 | **87.4** |
| **Bridge apply** | **~8.0** | **11.4** | **22.9** | **87.4 eps** |
| Failures / duplicates in window | 0 | 0 | 0 | **0 / 0** |
| Catch-up wall (400-burst) | 50 s | 35 s | 17.5 s | **4.58 s** |
| Peak lag | 329 | 213 | 218 | **0** |

**×3.8** vs Q1.3, **×11** vs the original S10 baseline. The quality-plan
target of **≥ 80 eps** is met on this burst profile. A later 2000-event drain
on the same Mac class cleared at **107.3 eps** (numeric ≥100 on a drain
window — [throughput-realpath-100eps-try-2026-07-17.md](throughput-realpath-100eps-try-2026-07-17.md));
the multi-hour *sustained* ≥100 claim remains open.

Peak lag 0 and Flink-hop == apply-rate mean the 400-burst drained end-to-end
inside one catch-up window: at this burst size the bridge no longer trails
the Flink hop, so the next ceiling probe needs a bigger burst or a sustained
produce rate (S11 soak / S13 scale), not another apply-path change.

## Batch amortization (Q1.3/Q1.4 DoD)

`agentflow_bridge_apply_batch_size` over the session (backlog drain of 400
events + the 400-event benchmark): **10 non-empty batches, 800 events,
mean 80 events/batch, p50 > 32** (cumulative buckets: 4 of 10 batches ≤ 32,
only 1 ≤ 16). The constant-round-trips apply path is genuinely amortizing —
p50 ≫ 1 under load.

## What Q1.4 changed (measured here for the first time)

- Session fold: one `SELECT … IN` + one multi-row `INSERT` per batch
  (was: read-modify-write per event).
- `users_enriched`: one grouped `SELECT` + one `INSERT` per batch
  (was: 2 HTTP round-trips per order with near-unique users).
- Net effect: a batch costs a **constant ~5–7 ClickHouse round-trips**
  independent of batch size. Semantics pinned by unit + integration tests
  (fold rules, idempotency, replay) — see `docs/serving-bridge.md`.

## Stand notes (for honest comparison)

- Same compose stand and protocol as the Q1.3 run (`throughput-realpath-q13-2026-07-09.md`).
- **1 Flink TaskManager** (`--scale flink-taskmanager=1`, 4 slots). The compose
  default of 2 replicas does not fit the 6 GiB VM next to Kafka + ClickHouse —
  with 2 TMs the JobManager gets OOM-killed (exit 137, reproduced this session).
  Prior S8/S10 runs also measured on 1 TM.
- Colima VM was rebooted before the run: the overnight stand had degraded
  (unrelated containers starved the VM to ~340 MiB available; the broker began
  timing out ListOffsets/FindCoordinator and the bridge consumer lost its
  assignment). On the fresh VM the broker answered instantly.
- Before the measurement window the bridge drained a replayed backlog:
  **5 052 duplicate events collapsed by the journal guard** (fresh job
  submission replays `orders.raw` from earliest), plus 400 real applies from an
  aborted earlier run. The measured window itself contains 0 duplicates.
- Produce rate (376 eps vs 647 in q13) varies with host load; it does not
  bound the apply measurement — the burst lands in Kafka before the drain
  window is evaluated.

## Reproduce

```bash
# Mac stand, repo at main, stack Kafka+CH+Redis+MinIO+Flink (1 TM), bridge on :9108
.venv/bin/python scripts/benchmark_throughput_realpath.py \
  --bootstrap 127.0.0.1:19092 --count 400 \
  --bridge-metrics http://127.0.0.1:9108/metrics --latency-samples 0
```

Gotchas that cost time this session (also in `docs/serving-bridge.md` /
runbook): never `docker start` a stopped Flink container (its command appends
to `config.yaml` on every start → duplicate keys → exit 1) — recreate with
`rm -sf` + `up -d`; give MinIO its own healthcheck window on a cold VM before
`up`-ing the Flink trio, or the dependency chain aborts.
