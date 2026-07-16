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

## Reproduce (drain window — this run)

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

## How to measure *sustained* ≥100 (not yet run)

The driver already supports paced produce (`--pace-eps`). Closing the sustained
claim is a **longer produce window** with lag remaining bounded while the
*target ingress* is ≥100 eps — not another unpaced backlog drain.

```bash
# Example: 15 min @ 100 eps target ≈ 90_000 events (wall ~900 s of produce)
# then catch-up; raise --catchup-timeout-seconds if lag is high.
# Pass criteria (proposed, not yet signed off as product bar):
#   - produce pace ≈ 100 eps (driver)
#   - bridge_apply_eps and flink_eps stay near the produce rate over the window
#   - lag_peak bounded and lag_end → 0 after catch-up
#   - apply_failures_delta == 0
.venv/bin/python scripts/benchmark_throughput_realpath.py \
  --bootstrap 127.0.0.1:19092 \
  --count 90000 --pace-eps 100 \
  --bridge-metrics http://127.0.0.1:9108/metrics \
  --latency-samples 0 --catchup-timeout-seconds 600 --no-md
```

**Stand constraints (Mac 6 GiB):** keep `--scale flink-taskmanager=1`; stop
co-tenants; do not claim multi-hour until a run of that length actually
finishes with healthy Flink. A 15 min paced arm is a first step; multi-hour
remains a separate soak-class exercise.

## Honest claim (what to put in SSOT)

| Claim | Status | Evidence |
|-------|--------|----------|
| Bridge can clear a realpath backlog at **≥ 80 eps** (400-burst) | **Met** (Q1.4) | this series / q14 |
| Bridge can clear a larger realpath drain at **≥ 100 eps** | **Met** on 2000-event arm (**107.3 eps**, flink = apply, 0 fail) | this doc |
| Bridge holds **≥ 100 eps sustained** for multi-hour / paced produce | **Not claimed** | still open; 4 h soak was ~47 eps *delivered* |

Do **not** collapse these three into “we do 100 eps in production.” The 107.3
figure is a **drain-window apply rate** after a finite produce, not a steady
ingress rate held for hours.
