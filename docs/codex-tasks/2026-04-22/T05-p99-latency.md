# T05 -- P99 entity latency optimization (rebased 2026-04-24)

**Priority:** P2 -- Estimate: 2-3 days (updated after re-baseline)

## Goal

Reduce p99 `/v1/entity/{type}/{id}` from **~936 ms** to **< 200 ms** (SLO target).

> **Historical context:** This task was originally written against stale hypotheses (sqlglot cache, DuckDB pool, orjson). The 2026-04-24 re-baseline (`A03`) proved those hypotheses do not match the measured hot path. This version replaces the old step order with an evidence-based backlog.

---

## Context

- **Repo:** `D:\DE_project\` (AgentFlow)
- **Endpoint:** `src/serving/api/routers/agent_query.py` (`get_entity`)
- **Current measured baseline (2026-04-24):**
  - p50: ~180 ms
  - p99: ~936 ms
  - throughput: ~68 RPS at concurrency 16
- **Top bottleneck:** `_get_pii_masker()` recreates `PiiMasker` on every request due to a Windows path-separator mismatch in the singleton check (~35 % of CPU time).
- **Secondary bottleneck:** DuckDB backend execution + `_last_updated` normalisation in `entity_queries.py` (~20-25 %).
- **Proven no-op for entity path:** sqlglot cache (SQL is f-string built, not parsed).

See full profile: [docs/perf/entity-profile-2026-04-24.md](../../perf/entity-profile-2026-04-24.md)

---

## Deliverables

Build as separate commits; each hypothesis is its own PR chunk. If a change gives < 5 % p99 improvement, drop it.

### Step 1 -- Fix PII masker singleton (commit: `perf: fix PiiMasker path comparison so singleton is reused`)

**Problem:** `str(_PII_MASKER.config_path) != config_path` is always True on Windows because `Path("config/pii_fields.yaml")` renders as `"config\\pii_fields.yaml"`.

**Fix:** Normalise the comparison, e.g.:

```python
from os import fspath
# ...
if _PII_MASKER is None or fspath(_PII_MASKER.config_path) != fspath(config_path):
    _PII_MASKER = PiiMasker(config_path)
```

Or use `Path(config_path).resolve()` on both sides.

**Verification:**
- Quick profile before/after on same machine within 5 minutes.
- Expected: p99 drops by 10-15 % (90-140 ms).
- Flamegraph after fix should show yaml composer/scanner frames disappear from top 10.

### Step 2 -- Re-profile and evaluate DuckDB execution layer (commit: TBD after measurement)

After Step 1 fixes the ~35 % masking overhead, re-run `profile_entity.py` + `py-spy`.

If `backend.execute()` or row materialisation becomes the new top frame:
- Evaluate connection pool reuse (`app.state.duckdb_pool` + `Depends`).
- Evaluate `_last_updated` normalisation caching (many rows share the same `updated_at` value).

If serialization (Pydantic / JSON) becomes top frame:
- Evaluate `orjson` for response encoding.

**Do not implement any of these without a post-Step-1 flamegraph proving they are now the bottleneck.**

### Step 3 -- Verify target and document (commit: `perf: verify p99 entity latency under target`)

- `docs/perf/entity-profile-after-<hypothesis>.md` for each merged hypothesis.
- Comparison table: metric -> before -> after -> delta %.
- Updated flamegraph(s).
- If p99 < 200 ms: update release gate docs and `perf-regression.yml`.
- If p99 > 200 ms after all proven hypotheses: document remaining bottleneck (likely DuckDB index or disk I/O) and propose next step (materialised view, read replica, etc.) as a **new architectural ticket**, not a no-op PR.

---

## Acceptance

- `make load-test` (or `pytest tests/load/test_entity.py --benchmark`) -- **p99 < 200 ms** on the reference hardware.
- `make test` green.
- `perf-regression.yml` in CI passes with new values.
- Before/after documents in `docs/perf/` reference the 2026-04-24 baseline.
- **No sqlglot-cache change is merged for the entity path unless it shows >= 5 % win on this baseline.**

---

## Notes

- **NEVER skip the 5 % threshold rule.** The old T05 wasted planning time on sqlglot-cache-first because the rule was not enforced against the actual hot path.
- **PII masking logic must stay functionally identical.** Only the caching / initialisation path changes.
- `orjson` stays in `[project.dependencies]`, NOT dev, if adopted.
- This task is now blocked only by implementation, not by measurement uncertainty.
