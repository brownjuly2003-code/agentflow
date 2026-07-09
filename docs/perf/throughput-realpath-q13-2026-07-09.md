# S10 re-measure after Q1.3 (ClickHouse-only batch apply)

> Measured: `2026-07-09T18:08Z` on `deproject-mac`  
> Code: `q13-ch-batch-apply` @ `88a3de4` / `5bd2189`  
> Path: **ClickHouse only** — no DuckDB on the bridge

## DuckDB clarification

| Store | Role |
|-------|------|
| **ClickHouse** | Production serving store the API reads. Bridge writes **only here**. |
| DuckDB | Local **demo / unit tests** only. Pre-Q1.2 the bridge also dual-wrote a throwaway in-process lake (never served). That is gone. |

## Results

| Arm | Pre-Q1.2 | Post-Q1.2 warm | **Post-Q1.3** |
|-----|--------:|---------------:|--------------:|
| Produce rate | 699 eps | 217 eps | **647 eps** |
| Flink hop | 7.97 | 11.4 | **22.9** |
| **Bridge apply** | **~8.0** | **11.4** | **22.9 eps** |
| Failures | 0 | 0 | **0** |
| Catch-up wall | 50 s | 35 s | **17.5 s** |
| Peak lag | 329 | 213 | **218** |

≈ **2.9×** vs original S10 baseline; **2.0×** vs post-Q1.2.  
Still **below** the quality-plan target of ≥80 eps — next levers: session RMW batching, Flink multi-TM, amortize CH round-trips further.

## What Q1.3 changed

- `apply_serving_batch`: multi-row `orders_v2` + multi-row `pipeline_events`
- `users_enriched` once per unique user in the batch (not per order)
- Journal last (crash mid-batch remains replayable)
- Bridge never opens DuckDB when `sink` is ClickHouse

## Reproduce

```bash
# Mac, main after merge, stack + bridge on :9108
.venv/bin/python scripts/benchmark_throughput_realpath.py \
  --bootstrap 127.0.0.1:19092 --count 400 \
  --bridge-metrics http://127.0.0.1:9108/metrics --latency-samples 0
```
