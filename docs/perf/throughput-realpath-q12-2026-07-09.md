# S10 re-measure after Q1.2 (CH-native apply, no scratch DuckDB)

> Measured: `2026-07-09T18:00:02+00:00` on `deproject-mac`  
> Code: `main` @ `5a7ed6f` (`skip_local_store` bridge path)  
> Driver: `scripts/benchmark_throughput_realpath.py`  
> Machine-readable: Mac `.artifacts/throughput/realpath-current.json` (warm run)

## Setup

Same product path as the pre-Q1.2 baseline
([`throughput-realpath.md`](throughput-realpath.md)):

```
produce(orders.raw) → Flink 2.3.0 → events.validated → bridge → ClickHouse
```

- Colima vz 6 GiB / 4 CPU, kind stopped before compose
- Bridge: standalone process, `SERVING_BACKEND=clickhouse`, metrics `:9108`
- Burst **400** `order.created`, unpaced; latency samples **0** (API not started)
- Warm run (stack + job already RUNNING after a cold pass)

## Results vs pre-Q1.2 baseline

| Arm | Pre-Q1.2 (S10) | Post-Q1.2 cold | **Post-Q1.2 warm (canonical)** |
|-----|---------------:|---------------:|-------------------------------:|
| Produce rate | 699 eps | 65.6 eps | **217 eps** |
| Flink hop rate | 7.97 eps | 6.13 eps | **11.4 eps** |
| **Bridge apply rate** | **~8.0 eps** | 6.13 eps | **11.4 eps** |
| Applied / dup / fail | 400 / 0 / 0 | 400 / 0 / 0 | **400 / 0 / 0** |
| Catch-up wall | 50.2 s | 65.2 s | **35.2 s** |
| Peak lag | 329 | 203 | **213** |

Cold run was noisy (Flink just reached RUNNING, produce throttled).  
**Warm run is the post-Q1.2 headline: bridge apply ≈ 11.4 events/s.**

## Reading

1. **Q1.2 is not a ×10 win.** Removing scratch DuckDB BEGIN/COMMIT
   moved the ceiling from ~8 → ~11 eps (~1.4×) on this stand — not to 80–100.
2. **Flink hop rate ≈ bridge apply rate** (both 11.4). After Q1.2 the
   dual-write tax is gone; the remaining shared ceiling is Flink hop and/or
   **per-event ClickHouse HTTP** (order upsert + user aggregate re-read +
   status journal + validated journal).
3. **Do not claim “hundreds of events/s”.** The honest product number remains
   low tens of events/s until batch CH writes (Q1.3) and/or multi-TM Flink
   (Q1.5) are measured.
4. Produce rate (217 warm / 699 baseline) is host/driver variance; it is not
   the product ceiling when Flink/bridge sit at ~11 eps.

## Verdict for the quality plan

| Item | Status |
|------|--------|
| Q1.2 code in main | yes (`5a7ed6f`) |
| Live re-measure | **done** — ~11.4 eps warm |
| Target ≥ 80 eps | **miss** — next lever Q1.3 (batch CH insert + amortize aggregate) |
| Stop-the-line (plan: if &lt;×5, don't mask) | **engaged** — fix write path further, don't inflate docs |

## Next code lever (Q1.3)

Per applied order the bridge still issues multiple HTTP calls to ClickHouse
inside `ClickHouseSink.upsert_order` / `record_pipeline_event`. Batch those
within `_apply_batch` and drop or amortize `_refresh_user_aggregate` under
burst load.
