# S10 paced produce @ 100 eps — 1-hour arm

> Measured: `2026-07-16T23:30Z` → `2026-07-17T00:30Z` on `deproject-mac`
> (Colima vz 6 GiB / 4 CPU). Code: `main` @ `b5d9ce0`.
> Path: Kafka → Flink stream_processor (**1 TM**) → `events.validated` →
> host `bridge_consumer` → ClickHouse.
> JSON: `/tmp/s10_paced100_1h.json` on the stand.

## Result

| Metric | Value |
|--------|------:|
| Produce | **100.0 eps** (360 000 events in 3600.0 s, paced) |
| Flink hop | **99.5 eps** (360 000 validated) |
| Bridge apply | **99.5 eps** (+360 000 applied over 3617 s wall incl. catch-up) |
| Failures / duplicates | **0 / 0** |
| Lag start → end | 0 → **0** |
| Lag peak | **1679** (recovered) |

**Gate (this arm):** produce ≥ 95, apply ≥ 90, flink ≥ 90, failures = 0,
duplicates < 5 000, lag_end ≤ 100 → **PASS**.

## Honest claim

| Claim | Status |
|-------|--------|
| Drain-window ≥100 | Met (107.3 @ 2000) — separate doc |
| Paced ~10 min @ 100 produce | Met (~96.5 apply) — 10 min doc |
| **Paced 1 hour @ 100 produce with apply/hop ≈100, lag → 0** | **Met (this doc)** |
| Multi-hour (e.g. 4 h+) sustained ≥100 | **Still open** |

Do **not** call this “multi-hour soak.” It is a **single continuous hour** of
paced ingress at the product target rate on the Mac compose stand.

## Stand hygiene (required)

Earlier 1h attempts failed for ops reasons, not apply-path capacity:

1. **Stale ClickHouse journal + Flink earliest replay** → tens of thousands of
   journal-guard **duplicates**, `applied≈0` for the benchmark window.
   **Fix:** `docker compose … down -v` for *this* project only before the arm.
2. **`docker compose up` stuck** waiting on a one-shot `kafka-init` that stayed
   Running after topics were created — unstick by removing the init container
   and bringing CH/redis separately.

## Reproduce

```bash
export PATH=$HOME/bin:/usr/local/bin:$PATH
# colima start --cpu 4 --memory 6 --vm-type vz
cd ~/agentflow-docker-check
docker compose -f docker-compose.yml -f docker-compose.flink.yml down -v
docker compose -f docker-compose.yml -f docker-compose.flink.yml \
  up -d --build --scale flink-taskmanager=1 flink-job-runner
docker compose -f docker-compose.yml -f docker-compose.flink.yml up -d clickhouse redis
# wait job RUNNING + CH ping; start bridge_consumer on :9108
.venv/bin/python scripts/benchmark_throughput_realpath.py \
  --bootstrap 127.0.0.1:19092 \
  --count 360000 --pace-eps 100 \
  --bridge-metrics http://127.0.0.1:9108/metrics \
  --latency-samples 0 --catchup-timeout-seconds 1200 --no-md
```

## Status

**1 h paced @ 100 eps: PASS** (produce 100.0 / flink 99.5 / apply 99.5,
zero failures/duplicates, lag ends at 0). Multi-hour remains open.
