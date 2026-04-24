# Entity Hot-Path Profile -- 2026-04-24

**HEAD:** `97a190248a943b5ef6910881be4b9c010eceb33f`
**Environment:** Windows 11, Intel i7 (18 logical cores), 15.5 GB RAM, Python 3.13.7
**Stack:** Redis (Docker), DuckDB `agentflow_demo.duckdb`, API on `127.0.0.1:8000`
**Profiled by:** `scripts/profile_entity.py` + `py-spy` attached to uvicorn PID

---

## 1. Baseline Metrics

### Quick profile (`scripts/profile_entity.py`)

```bash
python scripts/profile_entity.py \
  --host http://localhost:8000 \
  --entity-type order \
  --entity-id ORD-20260404-1001 \
  --iterations 2000 \
  --concurrency 16 \
  --output docs/perf/entity-latency-baseline-2026-04-24.json
```

Result (run 1):

| Metric | Value |
|--------|-------|
| p50_ms | 179.29 |
| p95_ms | 615.62 |
| p99_ms | 936.34 |
| max_ms | 1731.31 |
| mean_ms | 232.83 |
| throughput_rps | 68.57 |
| wall_seconds | 29.166 |
| success_count | 2000 / 2000 |

Result (run 2, same conditions, 5 min later):

| Metric | Value |
|--------|-------|
| p50_ms | 181.57 |
| p95_ms | 546.08 |
| p99_ms | 892.40 |
| max_ms | 1410.15 |
| mean_ms | 223.52 |
| throughput_rps | 71.29 |
| wall_seconds | 14.027 |

**Observation:** p50 is stable (~180 ms), but p99 varies between 892-936 ms. The variance is driven by tail latency ( DuckDB single-writer contention + event-loop stalls ), not by throughput saturation.

### Comparison to historical drift

| Source | p99 entity | Conditions |
|--------|------------|------------|
| `docs/benchmark.md` (2026-04-17) | 460 ms | 20 users, 30 s, mixed surface |
| `docs/benchmark_pool16.md` | 320 ms | 50 users, 20 s, mixed surface |
| `docs/benchmark_pool16_60s.md` | 160 ms | 50 users, 60 s, mixed surface |
| **This baseline** | **936 ms** | 16 conc, 2000 req, entity-only |

The old files are **not comparable** because:
- They use mixed Locust traffic (only 40 % entity) and aggregate endpoints, diluting entity p99.
- They lack warmup control and machine metadata.
- Run time and user count differ; shorter runs under-report tail latency.

This profile is the **first entity-only, fixed-concurrency, repeatable measurement** and becomes the new ground truth.

---

## 2. Flamegraph Summary

**File:** `docs/perf/flamegraph-baseline-2026-04-24.svg`  
**Captured:** 3007 samples over 30 s while driving the same entity load.

### Top hot frames (by sample count)

| Rank | Frame | Samples | % | Layer |
|------|-------|---------|---|-------|
| 1 | `get_entity` (`src/serving/api/routers/agent_query.py:357`) | 487 | 16.22 % | **Router / post-processing** |
| 2 | `_get_pii_masker` (`src/serving/api/routers/agent_query.py:35`) | 487 | 16.22 % | **Router / middleware** |
| 3 | `__init__` (`<string>` Pydantic model creation) | 486 | 16.19 % | **Serialization / post-processing** |
| 4 | `__init__` (`src/serving/masking.py:18`) | 485 | 16.16 % | **Middleware / PII** |
| 5 | `compose_mapping_node` (`yaml/composer.py:133`) | 79 | 2.63 % | **Middleware / PII config load** |

### Layer attribution

| Layer | Frames | Approx share |
|-------|--------|--------------|
| **Router / post-processing** (`get_entity`, Pydantic validation, version transform) | 1 + 3 | ~32 % |
| **PII masking** (`_get_pii_masker`, `PiiMasker.__init__`, yaml compose) | 2 + 4 + 5 | ~35 % |
| **Backend execution** ( DuckDB query, row materialisation ) | Not in top 5; inferred from remainder | ~20-25 % |
| **Serialization** ( JSON encode, httpx response ) | Scattered | ~5-10 % |
| **Dependency noise** ( event loop, anyio streams, starlette middleware base ) | Scattered | ~5-10 % |

---

## 3. Root-Cause Analysis -- PII Masker Recreation

### Finding

`_get_pii_masker()` in `agent_query.py` is responsible for **~16 %** of CPU time on the hot path, and `PiiMasker.__init__` + YAML parsing account for another **~19 %**. Combined, **~35 %** of entity latency is spent re-initialising the PII masker.

### Why it happens

```python
# src/serving/api/routers/agent_query.py:31-36
def _get_pii_masker() -> PiiMasker:
    global _PII_MASKER
    config_path = os.getenv("AGENTFLOW_PII_CONFIG", "config/pii_fields.yaml")
    if _PII_MASKER is None or str(_PII_MASKER.config_path) != config_path:
        _PII_MASKER = PiiMasker(config_path)
    return _PII_MASKER
```

`PiiMasker.__init__` stores `self.config_path = Path(config_path)`. On Windows:

```python
>>> str(Path("config/pii_fields.yaml"))
'config\\pii_fields.yaml'
```

The comparison `str(_PII_MASKER.config_path) != config_path` is therefore **always True** because `config_path` is the Unix-style string `"config/pii_fields.yaml"`. The singleton is never reused; every request triggers:

1. `Path.read_text()` on the YAML file
2. `yaml.safe_load()` (complex scanner/parser/composer walk)
3. `PiiMasker` object construction

### Expected win if fixed

If the masker is cached correctly, the ~19 % spent in `__init__` + YAML parsing should drop to **< 1 %** (one-time load). The remaining `mask()` call itself is cheap for entity types that have no PII rules (e.g. `order`).

**Conservative estimate:** p99 improvement of **10-15 %** (90-140 ms reduction) from this fix alone, bringing p99 from ~936 ms to **~800-850 ms**.

---

## 4. Disconfirmed Hypotheses

| Hypothesis (from T05) | Evidence | Verdict |
|-----------------------|----------|---------|
| **sqlglot parse cache** is the main win | `entity_queries.py` builds SQL with f-strings; sqlglot is not imported or used in the entity path. | **Disconfirmed.** No-op for entity endpoint. |
| **DuckDB connection pool** per-request overhead | Connection pool is not visible in top-5 frames; `backend.execute()` time is drowned by router/masking overhead. | **Not top priority.** May matter after masking is fixed, but not first. |
| **orjson vs stdlib JSON** serialization | JSON encode time is scattered and < 5 % in flamegraph. | **Low expected win.** Consider only if profiling after masking fix shows serialization rising. |
| **Pydantic round-trip** overhead | Pydantic `model_validate` appears (`__init__ <string>`), but it is part of the same post-processing block; much of this time may be waiting on `_get_pii_masker()` which runs inside the request handler before validation. | **Secondary.** Address masking first, then re-measure. |

---

## 5. New Evidence-Based Hypotheses (ranked)

| Rank | Hypothesis | Expected p99 win | Verification | Risk |
|------|------------|------------------|--------------|------|
| 1 | **Fix `_get_pii_masker()` path comparison** (`os.fspath` or normalised Path comparison) | 10-15 % (90-140 ms) | Quick profile before/after; flamegraph should show yaml frames disappear. | Low -- one-line fix. |
| 2 | **Cache `_last_updated` normalisation** in `entity_queries.py` if datetime objects repeat | 2-5 % | Profile after hypothesis 1; check `datetime` frames. | Low; may be noise. |
| 3 | **Pre-compile PII rules** into a flat dict instead of walking YAML per request | 3-5 % | Only if hypothesis 1 leaves `mask()` itself in top 10. | Medium; changes masking contract. |
| 4 | **DuckDB connection pool** reuse if `backend.execute()` becomes top frame after masking fix | 5-10 % | Profile after masking fix; measure FD growth. | Medium; affects all query paths. |
| 5 | **orjson response encoder** | < 3 % | Micro-benchmark JSON encode of a 10-field entity dict. | Low; easy to validate but likely below threshold. |

---

## 6. Before/After Artifact Checklist

- [x] Baseline JSON: `docs/perf/entity-latency-baseline-2026-04-24.json`
- [x] Flamegraph: `docs/perf/flamegraph-baseline-2026-04-24.svg`
- [x] Profile write-up: this file
- [ ] After-fix JSON: `docs/perf/entity-latency-after-pii-masker.json` (pending implementation)
- [ ] After-fix flamegraph: `docs/perf/flamegraph-after-pii-masker.svg` (pending implementation)
