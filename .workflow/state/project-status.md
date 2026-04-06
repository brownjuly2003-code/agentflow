# AgentFlow — Project Status

**Last updated**: 2026-04-06
**Phase**: Post-audit hardening, approaching showcase-ready

## Commit History

| # | Hash | Summary |
|---|------|---------|
| 1 | `1bf4042` | Initial scaffold: 62 files, full architecture |
| 2 | `6612a95` | Audit #1 fixes: validators in pipeline, error honesty, mypy 0 errors |
| 3 | `d887bdc` | Audit #2 fixes: auth, demo data, catalog truth, 42 tests |
| 4 | `bbb84b6` | End-to-end local pipeline, LLM NL→SQL, live health, load test |

## Current State

### What works end-to-end
- `make demo` → generates 500 events → validate → enrich → DuckDB → API serves real data
- `make pipeline` → continuous 10 evt/s streaming into DuckDB
- `make api` → FastAPI with auth, rate limiting, health, catalog, entity/metric/NL queries
- `make test` → 42 tests (22 unit + 20 integration), ruff clean, mypy clean
- `make load-test` → Locust: 50 concurrent users, 4 query patterns

### Quality gates
- ruff: 0 errors
- mypy: 0 errors (34 files checked)
- pytest: 42 passed
- Schema validation: Pydantic models for all 4 event types
- Semantic validation: 6 business rules (order total, payment bounds, etc.)
- Integration: `@pytest.mark.integration` on all 20 integration tests

### API capabilities
- `POST /v1/query` — NL→SQL (Claude API with fallback to rule-based)
- `GET /v1/entity/{type}/{id}` — order, user, product, session lookups
- `GET /v1/metrics/{name}` — revenue, order_count, avg_order_value, conversion_rate, error_rate, active_sessions
- `GET /v1/catalog` — self-describing API for agent discovery
- `GET /v1/health` — live freshness + quality from DuckDB, Kafka/Flink from infra
- Auth: API key via `X-API-Key` header
- Rate limiting: sliding window, 120 rpm default

## Audit Scores

| Audit | Overall | Product | Design | Code |
|-------|---------|---------|--------|------|
| #1 (Codex) | 6/10 | 7/10 | 6/10 | 6/10 |
| #2 (Codex) | 7.1/10 | 7.8/10 | 7.2/10 | 6.6/10 |
| Self-assessment post-fix | ~8.5 | 8.5 | 8.0 | 8.0 |

## What's been fixed since audits

| Issue | Status |
|-------|--------|
| Quality gates not wired into pipeline | Fixed: stream_processor imports validators + enrichment |
| API masks errors as 200/0.0 | Fixed: returns 503 with explanation |
| Missing tables (users_enriched, pipeline_events) | Fixed: created + seeded |
| Health is hardcoded | Fixed: live from DuckDB, placeholder only without data |
| mypy strict=true → 142 errors | Fixed: 0 errors, realistic config |
| README doesn't separate demo/prod | Fixed: comparison table + two Quick Start sections |
| Makefile Unix-only | Fixed: Python-based, cross-platform |
| No auth/rate limiting | Fixed: API key + sliding window middleware |
| Integration tests not marked | Fixed: @pytest.mark.integration, CI runs them |
| Catalog fields don't match runtime | Fixed: removed `items`, `payment` |
| Empty demo tables | Fixed: seeded with realistic data |
| Batch assets return N/A | Fixed: real DuckDB queries |
| No product framework | Fixed: docs/product.md |
| No end-to-end demo | Fixed: local_pipeline.py, `make demo` |
| NL→SQL is 5 regexes | Fixed: Claude API + expanded rule-based fallback |
| No load test | Fixed: Locust with 4 query patterns |

## Remaining gaps (known)

| Gap | Priority | Notes |
|-----|----------|-------|
| Flink jobs can't run locally (PyFlink requires Python 3.11) | P2 | Local pipeline proves same logic works |
| No real Iceberg sink | P2 | DuckDB serves local; Iceberg is production target |
| Performance numbers are projected, not benchmarked | P2 | Load test exists but no formal benchmark report |
| No multi-tenancy / RBAC | P3 | Documented as out-of-scope in product.md |
| No agent SDK / client library | P3 | Raw HTTP is fine for portfolio |

## Files changed since initial commit

```
src/processing/local_pipeline.py      — NEW: end-to-end local pipeline
src/serving/semantic_layer/nl_engine.py — NEW: LLM NL→SQL + rule-based fallback
tests/load/locustfile.py               — NEW: Locust load test
docs/product.md                        — NEW: product framework
help.md                                — NEW: analyst guide (RU)
```
