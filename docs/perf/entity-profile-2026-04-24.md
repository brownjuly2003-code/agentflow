# Entity Hot-Path Profile -- 2026-04-24

**HEAD:** `97a190248a943b5ef6910881be4b9c010eceb33f`
**Environment:** Windows 11, Intel i7 (18 logical cores), 15.5 GB RAM, Python 3.13.7
**Stack:** Redis (Docker), DuckDB `agentflow_demo.duckdb`, API on `127.0.0.1:8000`
**Profiled by:** `scripts/profile_entity.py` + `py-spy` attached to uvicorn PID
**Latest refresh:** requested `a3ecd38`, measured on `5b57cf4` (serving code/config/scripts unchanged from `a3ecd38`; later commits touch CI, version metadata, and Iceberg compose)

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

## 3. CLOSED -- PII Masker Recreation

### Finding

`_get_pii_masker()` in `agent_query.py` is responsible for **~16 %** of CPU time on the hot path, and `PiiMasker.__init__` + YAML parsing account for another **~19 %**. Combined, **~35 %** of entity latency is spent re-initialising the PII masker.

**Status:** closed by `220f94c` (`perf(api): normalize PII masker cache key via pathlib.Path`). The current flamegraph no longer shows `_get_pii_masker()` or `PiiMasker.__init__` as top frames.

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

### Observed win after fix

`docs/perf/entity-latency-after-pii-masker-cache.json` recorded p99 **360.97 ms** on `220f94c`, down from **936.34 ms** baseline (-61 %). That made the old PII-cache hypothesis complete, but nightly p99 < 200 ms is still not satisfied.

---

## 4. Hot frames after PII masker fix

**Artifacts:**
- Flamegraph: `docs/perf/flamegraph-after-pii-masker-cache.svg`
- Latency JSON: `docs/perf/entity-latency-a3ecd38-flamegraph.json`

**Capture:** `py-spy record -o docs/perf/flamegraph-after-pii-masker-cache.svg --pid <uvicorn_pid> --duration 45` while running the canonical 2000-iteration, concurrency-16 entity profile. Duration was extended from 30 s because the measured window now takes ~28 s and needs full coverage.

### Latency check

| Metric | After PII cache fix | Fresh flamegraph run | Delta |
|--------|---------------------|----------------------|-------|
| p50_ms | 56.65 | 165.89 | +193 % |
| p95_ms | 233.78 | 620.51 | +165 % |
| p99_ms | 360.97 | 962.22 | +167 % |
| throughput_rps | 193.73 | 70.49 | -64 % |
| wall_seconds | 10.324 | 28.373 | +175 % |

This is **not** within the expected +/-10 % band. Stack checks found Redis healthy, fixture row present, zero `query_cache_unavailable` warnings, and no serving-code delta from `a3ecd38`. The flamegraph explains the drift: the new dominant path is tenant table qualification and DuckDB metadata checks, not PII masking.

### Top hot frames (by sample count)

| Rank | Frame | Samples | % | Layer |
|------|-------|---------|---|-------|
| 1 | `get_entity` (`src/serving/semantic_layer/query/entity_queries.py:39`) | 1976 | 45.01 % | **Entity query / backend call** |
| 2 | `execute` (`src/serving/backends/duckdb_backend.py:48`) | 1953 | 44.49 % | **DuckDB execution** |
| 3 | `get_entity` (`src/serving/semantic_layer/query/entity_queries.py:27`) | 1009 | 22.98 % | **SQL/table resolution** |
| 4 | `_qualify_table` (`src/serving/semantic_layer/query/sql_builder.py:46`) | 600 | 13.67 % | **Tenant table qualification** |
| 5 | `load` (`src/ingestion/tenant_router.py:48`) | 442 | 10.07 % | **Tenant YAML parse** |

Relevant child frames: `_table_columns` (`src/serving/semantic_layer/query/engine.py:65`) at 335 samples / 7.63 %, `table_columns` (`src/serving/backends/duckdb_backend.py:71`) at 316 / 7.20 %, and YAML composer frames under `TenantRouter.load` at ~8-10 %. Uvicorn access logging is visible (`logging.info`, 105 / 2.39 %) but not the main bottleneck.

---

## 5. Disconfirmed / Re-ranked Hypotheses

| Hypothesis (from T05) | Evidence | Verdict |
|-----------------------|----------|---------|
| **sqlglot parse cache** is the main win | `entity_queries.py` builds SQL with f-strings; sqlglot is not imported or used in the entity path. | **Disconfirmed.** No-op for entity endpoint. |
| **DuckDB pool / metadata contention** | `execute()` is now a top cumulative frame, and `_table_columns` / `table_columns` together account for ~7-8 % while table qualification probes schemas. | **Re-opened, but scoped to metadata/table-column checks first.** |
| **orjson vs stdlib JSON** serialization | JSON encode is not a visible top frame; response send/logging is visible but below table qualification and DuckDB metadata. | **Low expected win.** Below the 5 % perf threshold for T24. |
| **usage-DB single-writer contention** | Auth started in open mode (`configured_keys: 0`), and no usage-recording frame appears in the flamegraph. | **Not this run's bottleneck.** Re-test only with configured API keys. |
| **Pydantic round-trip** overhead | Pydantic construction is no longer a top frame after the PII fix. | **Not a near-term candidate.** |

---

## 6. Updated Evidence-Based Backlog (ranked)

| Rank | Hypothesis | Predicted p99 win | Rationale from flamegraph | Cost |
|------|------------|-------------------|--------------------------|------|
| 1 | **Cache tenant config + resolved table qualification** (`TenantRouter.load()`, `has_config()`, and no-tenant schema scan) | 20-35 % | `_qualify_table` 13.67 %, `TenantRouter.load` / `yaml.safe_load` 10.07 %, repeated `Path.exists()` / YAML parse on the request path. Removing synchronous file/YAML work should also reduce event-loop tail amplification. | Medium |
| 2 | **Cache DuckDB table-column metadata used by tenant qualification** | 8-15 % | `_table_columns` 7.63 % and `table_columns` 7.20 % are child frames of `_qualify_table`; repeated schema probes happen before the actual entity query. | Medium |
| 3 | **Investigate DuckDB execution pool/connection contention after qualification cache** | 5-10 % | `duckdb_backend.execute` is 44.49 % cumulative, but current child evidence points first to qualification and metadata probes rather than pool acquisition itself. | Medium |
| 4 | **Reduce response access logging / send overhead in benchmark mode** | 3-5 % | `logging.info` is 2.39 % and send/middleware frames are visible, but this is below the tenant/DuckDB metadata path. | Low |
| 5 | **Switch entity response JSON to orjson** | < 3 % | JSON serialization does not appear as a top frame in the fresh flamegraph. | Low |
| 6 | **Usage-DB single-writer optimization** | 0 % for open-auth run; unknown with keys | Auth was open (`configured_keys: 0`), so usage writes were not on the measured hot path. | Medium |

---

## 7. Next candidate

**Selected for T24:** cache tenant config and resolved table qualification.

Why this one: it is the highest actionable post-PII frame cluster, with direct evidence from `_qualify_table`, `TenantRouter.load`, YAML parsing, and table-column probes. It is also narrower than a general DuckDB pool rewrite: T24 can first remove per-request config/YAML/schema-resolution work, then re-profile to see whether true DuckDB execution remains top.

Why not the others: orjson is not visible; usage-DB writes are absent in this open-auth benchmark; access logging is too small; a broad DuckDB pool change should wait until table qualification and metadata probes are out of the flamegraph.

---

## 8. Before/After Artifact Checklist

- [x] Baseline JSON: `docs/perf/entity-latency-baseline-2026-04-24.json`
- [x] Flamegraph: `docs/perf/flamegraph-baseline-2026-04-24.svg`
- [x] Profile write-up: this file
- [x] After-PII JSON: `docs/perf/entity-latency-after-pii-masker-cache.json`
- [x] Fresh latency JSON: `docs/perf/entity-latency-a3ecd38-flamegraph.json`
- [x] Fresh flamegraph: `docs/perf/flamegraph-after-pii-masker-cache.svg` (4390 SVG samples / py-spy reported 4391)
