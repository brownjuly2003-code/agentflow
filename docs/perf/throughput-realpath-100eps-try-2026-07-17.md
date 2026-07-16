# S10 stretch try — ≥100 eps bridge apply (larger burst)

> Measured: `2026-07-16T22:28–22:29Z` on `deproject-mac` (Colima vz 6 GiB / 4 CPU,
> macOS 13.7.8 Intel). Code: Mac checkout `88c9804` (Q1.4 apply path already on
> `main`). Path: **ClickHouse only** — Kafka → Flink stream_processor (1 TM) →
> `events.validated` → host `bridge_consumer` → ClickHouse.
> Machine-readable: `/tmp/s10_burst400.json`, `/tmp/s10_burst2000.json` on the
> stand (also copied under Windows `.tmp/` for this session).

## Results

| Arm | Q1.4 (400, 2026-07-10) | **This run 400** | **This run 2000** |
|-----|----------------------:|-----------------:|------------------:|
| Produce rate | 376 eps | 524 | **2216** |
| Flink hop | 87.4 | 65.0 | **107.3** |
| **Bridge apply** | **87.4** | **65.0** | **107.3 eps** |
| Failures / duplicates in window | 0 / 0 | 0 / 0 | **0 / 0** |
| Catch-up wall | 4.58 s | 6.15 s | **18.65 s** |
| Peak lag | 0 | 0 | **187** |

**Headline:** on a **2000-event burst**, bridge apply = Flink hop = **107.3 eps**
(0 failures, 0 duplicates in the measured window). That crosses the numeric
**≥ 100 eps** stretch bar for a single drain window on this Mac stand.

The cold **400** arm landed lower (65 eps) than Q1.4's 87.4 — first measure
right after compose/job bring-up on a busy 6 GiB VM; the 2000 arm ran
immediately after and is the better loaded sample.

## What this does *not* claim

STATUS's open item is **sustained** (not burst) bridge apply ≥ 100 eps. This
run is still a **finite produce + catch-up drain**, not a multi-hour produce
rate held above 100 eps with bounded lag. Closing the sustained claim needs a
longer paced produce (or soak profile) with a healthy Flink hop for the whole
window — same protocol caveats as Q1.4 / S11.

What it *does* show: with a larger backlog (2000 vs 400), the Q1.4 constant
round-trip apply path can clear at **>100 eps** end-to-end on the same class of
Mac compose stand, and the bridge is not trailing Flink on that window
(`flink_eps == bridge_apply_eps`).

## Stand notes

- Compose: `docker-compose.yml` + `docker-compose.flink.yml`,
  `--scale flink-taskmanager=1` (2 TMs OOM the 6 GiB VM — same as Q1.4).
- First `up` raced MinIO health (job-runner deferred); re-`up` minio-init +
  job-runner; Flink job `RUNNING` before measure.
- Bridge: host `.venv` process, `KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092`,
  metrics `:9108`, `config/serving.yaml` (ClickHouse).
- Co-tenant containers left stopped; no `docker system prune`.

## Reproduce

```bash
export PATH=$HOME/bin:/usr/local/bin:$PATH
# colima start --cpu 4 --memory 6 --vm-type vz
cd ~/agentflow-docker-check
docker compose -f docker-compose.yml -f docker-compose.flink.yml \
  up -d --build --scale flink-taskmanager=1 \
  kafka kafka-init minio minio-init redis clickhouse \
  flink-jobmanager flink-taskmanager flink-job-runner
# wait CH/Flink healthy + job RUNNING; start bridge_consumer on :9108
.venv/bin/python scripts/benchmark_throughput_realpath.py \
  --bootstrap 127.0.0.1:19092 --count 2000 \
  --bridge-metrics http://127.0.0.1:9108/metrics --latency-samples 0 --no-md
```

## Status

**Stretch numeric bar (≥100 eps on a realpath drain):** observed **107.3 eps**
on the 2000-burst arm. **Sustained multi-hour claim:** still open.
