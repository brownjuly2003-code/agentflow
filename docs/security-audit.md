# Security Audit Report

**Project:** AgentFlow
**Document date:** 2026-04-18
**Repository snapshot reviewed:** 2026-04-18
**Audience:** engineering, security review, enterprise due diligence

## 1. Executive Summary

AgentFlow exposes a public FastAPI surface for AI agents and tenant-owned integrations. The current repository shows a security posture centered on typed request validation, tenant-scoped access control, API-key authentication, rate limiting, PII masking on responses, SQL safety guards for NL-to-SQL, and CI-based dependency and image scanning.

The codebase is strongest at application-layer controls that can be validated directly in source: auth, authorization, request filtering, security headers, contract evolution, replay safety, and auditability of API usage. The weakest areas are the controls that typically require external infrastructure or third-party attestation. In this repository snapshot there is no evidence of an external penetration test or demonstrated generalized secrets manager integration. Local DuckDB files can be opened through an optional encrypted attach path when an operator supplies encryption key material, but the default remains backward-compatible and unencrypted.

External pen-test attestation status as of 2026-05-06: not present. Use
`docs/operations/external-pen-test-attestation-handoff.md` for the checklist
required before any third-party pen-test claim.

Automated posture channel (2026-06-05): the repository now publishes an
OpenSSF Scorecard result (`.github/workflows/scorecard.yml`) and carries a
prepared OpenSSF Best Practices self-assessment
(`docs/operations/openssf-security-posture.md`). Both are $0 posture signals —
an automated heuristic score and a maintainer self-certification respectively —
and are kept explicitly distinct from a third-party penetration test, which is
still not present and not claimed.

Threat model assumed by the current implementation:
- untrusted external callers using `X-API-Key`
- tenant isolation requirements across shared serving infrastructure
- AI agents issuing natural-language queries that must not escape allowed tables or mutate data
- operational abuse such as brute-force authentication attempts and burst traffic

## 2. Authentication and Authorization

The API uses tenant-bound API keys plus a separate admin secret for `/v1/admin/*`. API key material can be stored either as plaintext runtime values or as bcrypt hashes. The default security policy sets bcrypt rounds to `12`, which is aligned with a modern password-hashing baseline for application secrets.

Rotation support is implemented in the auth layer. Keys have `key_id`, `previous_key_hash`, `previous_key_active_until`, and explicit grace-period behavior. Admin rotation endpoints expose create, rotate, rotation-status, and revoke-old flows. The auth middleware also records endpoint usage per tenant/key, which gives the system a concrete audit trail for key activity and key-slot transitions.

Authorization is layered on top of authentication:
- admin endpoints require `X-Admin-Key`
- entity access can be restricted per key through `allowed_entity_types`
- request context binds `tenant_id` to the authenticated tenant
- serving paths use that tenant context when querying tenant-scoped data

Evidence: `src/serving/api/auth/manager.py`, `src/serving/api/auth/middleware.py`, `src/serving/api/auth/key_rotation.py`, `tests/integration/test_rotation.py`

## 3. Tenant Isolation

**This section previously described a mechanism that did not work.** It said the boundary was a schema qualification — `TenantRouter` mapping a tenant to a DuckDB schema name, and the SQL builder qualifying tables into `"acme"."orders_v2"`. Nothing in `src/` ever issued `CREATE SCHEMA`, so that relation did not exist at runtime and every authenticated entity read failed; on ClickHouse the same qualification named a database nobody creates. The suite was green because the shipped keys named a tenant absent from `config/tenants.yaml`, so the qualification resolved to nothing and silently did not apply. A boundary no test can tell apart from its own absence is not a boundary. See ADR-004.

The boundary is now the `tenant_id` **column**, on both stores, and it is part of each serving table's **write key** — `ORDER BY (tenant_id, <pk>)` on ClickHouse, `PRIMARY KEY (tenant_id, <pk>)` on DuckDB. That distinction is load-bearing: with a single-column key, two tenants' rows sharing an `order_id` are two versions of *one* ReplacingMergeTree row, and the later insert destroys the earlier. No read-side filter can undo that, so a filter alone was never sufficient.

Reads pass through one chokepoint. `SQLBuilderMixin._qualify_table` returns a tenant-filtered sub-select rather than a name, `_scope_sql` performs the same substitution inside metric templates and NL-generated SQL via the sqlglot AST, the search index carries the tenant on each document and filters before scoring, and the journal applies its own predicate. An unscoped read against a store that holds more than one tenant's rows is refused (`503`), not answered.

What the evidence supports today:

- **DuckDB** — proven. Two tenants with identical `order_id` resolve to different rows; cross-tenant lookups return `404`; aggregates sum only the caller's rows; an unscoped read fails closed. Property tests assert the invariant over generated tenant and entity ids, not just the two-tenant example.
- **ClickHouse** — the same model is implemented and provisioned (`assert_tenant_key()` refuses to serve a store still on the old sorting key; `provision --migrate` rebuilds one). The adversarial two-tenant suite for it is `tests/integration/test_clickhouse_tenant_isolation_live.py`, which requires a live server and runs on the CI integration job. **Until that suite is green on a real server, treat multi-tenant ClickHouse as unproven and do not claim it.**

It does not support broader claims such as end-to-end isolation across every external dependency.

Evidence: `docs/decisions/004-tenant-id-column-over-schema-per-tenant.md`, `src/tenancy.py`, `src/serving/semantic_layer/query/sql_builder.py`, `src/serving/backends/clickhouse_backend.py`, `tests/integration/test_tenant_isolation.py`, `tests/property/test_tenant_isolation_properties.py`, `tests/integration/test_clickhouse_tenant_isolation_live.py`

## 4. Input Validation and Contract Safety

Typed validation is pervasive in the API surface. FastAPI request bodies and query parameters are defined with Pydantic models across agent, batch, alert, webhook, dead-letter, SLO, and contract endpoints. Validation constraints are used for lengths, enums, numeric ranges, and optional structures.

The ingestion schemas add cross-field semantics beyond shape validation. `OrderEvent` verifies that `total_amount` matches the sum of line items, payment timestamps are normalized to UTC and rejected if too far in the future, and product pricing rejects negative values. This matters because it prevents upstream data corruption from turning into trusted downstream state.

Schema contract evolution is implemented through a contract registry plus version-aware validation and diff endpoints. The API versioning layer also exposes deprecation metadata through headers and supports tenant-level version pins, which reduces the blast radius of backward-incompatible changes.

Evidence: `src/ingestion/schemas/events.py`, `tests/unit/test_event_schemas.py`, `src/serving/semantic_layer/contract_registry.py`, `src/serving/api/routers/contracts.py`, `src/serving/api/versioning.py`

## 5. SQL Injection Protection and Query Safety

The serving layer uses two complementary patterns for SQL safety.

First, the hot-path entity and metric lookups pass untrusted values as query parameters rather than interpolating them into SQL text. Injection-focused unit tests assert that payloads such as `'; DROP TABLE ...` stay in parameter arrays and never appear in the generated SQL.

Second, the NL-to-SQL surface validates translated SQL with `sqlglot`. The validator only permits a single `SELECT` statement, rejects DDL and DML node types, and rejects unknown tables outside the allowlist and CTE names. Tenant scoping is then applied through AST-aware rewriting in `_scope_sql`, which is materially safer than regex replacement.

The repository also documents intentional `# nosec B608` suppressions only on trusted identifier paths where identifiers come from internal catalog/config allowlists rather than user-controlled input.

### 5.1 Interpolated-SQL site inventory (A-4)

Audit finding A-4 flagged the dynamic-SQL surface as "one careless edit away from a hole". Every `# nosec B608` suppression in `src/` was reviewed and is **safe by construction**:

- Interpolated **identifiers** come from a fixed in-code allowlist, the semantic catalog, trusted backend config, live schema introspection (`PRAGMA table_info`), `_IDENTIFIER_RE`, or `sqlglot` validation.
- Interpolated **values** are either bound as `?` parameters, fixed literals, integers, or regex-extracted tokens that exclude SQL metacharacters and are additionally quoted via `_quote_literal` / `_sql_str_literal`.

No site interpolates unbound, unquoted request data. There are **no Class-A (migratable value-interpolation) sites remaining**: the hot entity/metric paths already bind values (`use_query_params` on DuckDB, `_quote_literal` elsewhere) and the operational routers already pass values through `?`. The remaining suppressions are Class-B (identifiers / structural fragments that cannot be parameterized). The `PostgresControlPlaneStore` sites added by ADR 0010 slice 5 (`control_plane/postgres.py`, reviewed 2026-07-03) interpolate only a table name that is a module literal at exactly two call sites; every value binds via `%s`.

**audit P0-3 (2026-07-11).** The five journal sites moved out of `routers/lineage.py` (1) and `routers/slo.py` (4) into `semantic_layer/journal.py`, which reads `pipeline_events` through the *active* serving backend instead of a private DuckDB cursor. The interpolated surface is unchanged in kind, and smaller in spread: every fragment is an identifier taken from a live schema probe (`table_columns`) against a fixed allowlist — the time column, the nullable-column fallbacks — plus the SLO quantile, a float from `config/slo.yaml`. **Values still never interpolate:** `JournalReader._value()` binds them as `?` on DuckDB and `_quote_literal`-escapes them on ClickHouse, whose `execute(params=...)` is a documented no-op. So `entity_id`, which arrives in the URL path, binds exactly as it did before the move. The one exception is the time window (`'7 days'`), inlined on both backends because `INTERVAL ?` is a DuckDB syntax error and `CAST(? AS INTERVAL)` has no ClickHouse translation — it is derived from an `int` in `config/slo.yaml` and is never request data. `entity_queries.py` gained the bulk entity scan the search index used to run on the raw connection (catalog-defined table name, `int()` limit, no values).

The number of suppressions per file is pinned by `test_interpolated_sql_nosec_surface_is_pinned` — a new site (even inside an already-listed file) or a new file fails CI and forces a review. Each suppression's per-line rationale comment is enforced by `test_nosec_comments_carry_reason`.

| Site | Interpolated | Why safe (Class B — safe by construction) |
|------|--------------|--------------------------------------------|
| `semantic_layer/nl_engine.py:110,163` | `oid`, `uid` (values) | regex `ORD-[\w-]+` / `USR-\d+` exclude quotes; additionally quoted via `_sql_str_literal`; covered by `test_nl_engine_injection.py` |
| `semantic_layer/nl_engine.py:116,126,149` | `window` (value) | `_extract_window` numeric allowlist (`\d+ <unit>` or constant); quoted via `_sql_str_literal` |
| `semantic_layer/nl_engine.py:139` | `limit` (value) | parsed `int()` from the question text |
| `api/routers/lineage.py:103` | `select_columns`, `time_column` (identifiers) | column names are in-code literals gated by `PRAGMA table_info`; values bound as `?` |
| `api/routers/slo.py:109,123,143,160` | `time_column` (identifier) | fixed allowlist `processed_at`/`created_at`; window/tenant bound via `CAST(? AS INTERVAL)` / `?` |
| `api/routers/stream.py:45` | `select_columns` (identifiers) | in-code literals gated by `PRAGMA table_info`; filters bound as `?` |
| `api/webhook_dispatcher.py:315` | `order_by` (identifier) | fixed allowlist `processed_at`/`created_at`/`event_id`; tenant bound as `?` |
| `backends/clickhouse_backend.py:293,306,326,344,359,375` | `self._database` + fixed table names | database from trusted backend config; table names and VALUES are in-code literals (demo seed) |
| `backends/duckdb_backend.py:94` | `table_name` (identifier) | guarded by `_IDENTIFIER_RE.match` (bare identifier or `schema.identifier`) |
| `backends/duckdb_backend.py:116` | `sql` (full statement) | `sqlglot.parse` must yield exactly one `exp.Select` before `EXPLAIN` |
| `semantic_layer/query/entity_queries.py:31,133,196` | table / primary_key / entity_type | identifiers via `_quote_identifier` from catalog; values via `_quote_literal` or `?` (`use_query_params` on DuckDB) |
| `semantic_layer/query/nl_queries.py:133,138` | `sql` subquery, `limit`/`offset` | `sql` prevalidated by `validate_nl_sql` (sqlglot single SELECT); `limit` bounded 1..1000, `offset` decoded int |
| `semantic_layer/search_index.py:152` | `entity.table` (identifier) | table name from the semantic catalog `EntityDefinition`, not request data |
| `orchestration/dags/daily_batch.py:148` | `table` (identifier) | iterates a fixed in-code health-check list |

Evidence: `src/serving/semantic_layer/sql_guard.py`, `src/serving/semantic_layer/query/sql_builder.py`, `src/serving/semantic_layer/nl_engine.py`, `tests/unit/test_query_engine_injection.py`, `tests/unit/test_sql_guard.py`, `tests/unit/test_nl_engine_injection.py`, `tests/unit/test_security_tooling_policy.py`

## 6. Rate Limiting and Abuse Protection

Rate limiting exists at two levels:
- per-key request quotas enforced through `RateLimiter`
- per-IP throttling for repeated failed authentication attempts

`RateLimiter` uses Redis when available and falls back to an in-memory sliding window when Redis is unavailable or intentionally disabled. The auth middleware returns `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `Retry-After` headers, so clients can adapt to the policy rather than blindly retrying.

The SDKs also include resilience primitives, specifically retry policy handling and a circuit breaker. This is not a server-side abuse control by itself, but it does reduce retry storms and repeated hammering of degraded endpoints by well-behaved clients.

Evidence: `src/serving/api/rate_limiter.py`, `src/serving/api/auth/middleware.py`, `sdk/agentflow/client.py`, `sdk-ts/src/client.ts`, `tests/unit/test_sdk_circuit_breaker.py`

## 7. Data Protection and Privacy Controls

> **Superseded (2026-07-01).** The response-side PII masking / deny-gate described
> in this section has been **removed**. The demo serving warehouse holds no PII
> (`users_enriched`/`orders_v2` carry only analytics columns), so the machinery
> guarded an empty surface. Real contact PII lives only in the DV2 business vault
> and is governed engine-side there (ClickHouse row/column policies — ADR 0006
> Phase 2). The paragraph below is retained as the point-in-time record.

Response-side PII masking is implemented in `PiiMasker` and applied on entity responses and NL-query results. Masking behavior is configured through `config/pii_fields.yaml`, supports multiple strategies (`partial`, `full`, `hash`), and allows explicit tenant exemptions for internal tenants. When masking is applied, the API sets `X-PII-Masked: true`.

Security headers are applied centrally and include:
- `Strict-Transport-Security`
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Referrer-Policy`

These controls improve baseline browser-facing hardening for docs/admin surfaces. TLS termination is intentionally delegated to an upstream edge or ingress layer; the FastAPI application applies HTTP-layer security controls behind that boundary.

Evidence: `src/serving/masking.py`, `src/serving/api/routers/agent_query.py`, `src/serving/api/security.py`, `tests/unit/test_masking.py`

## 8. Supply Chain and CI Controls

The repository includes a dedicated security workflow in GitHub Actions:
- Bandit for Python static analysis with a tracked baseline diff
- Safety for dependency vulnerability scanning
- Trivy for container image scanning and CycloneDX SBOM generation

The Bandit baseline currently records a historical `B310` finding in `src/serving/backends/clickhouse_backend.py`. SQL construction findings are not globally suppressed; reviewed identifier construction is handled through narrow suppressions and tests.

Helm defaults no longer embed production-shaped API-key verifier hashes. Operators can render a chart-managed Secret for local use or mount an existing Kubernetes Secret, which is friendlier to External Secrets Operator, Sealed Secrets, or equivalent workflows.

Evidence: `.github/workflows/security.yml`, `.bandit`, `.bandit-baseline.json`, `docs/helm-deployment.md`

## 9. Operational Security and Auditability

Operationally, the repo shows several useful security-facing controls:
- API usage is written to `api_usage` with tenant, key name, endpoint, key ID, and key slot
- admin analytics endpoints can inspect usage, anomalies, latency, and top entities/queries
- the runbook includes response procedures for API unavailability, pipeline lag, dead letters, webhook failures, alert storms, and stuck key rotation

This provides a credible audit and incident-response starting point for a small team. It is notably better than a pure demo API with no usage telemetry.

What is not evidenced in this repository snapshot:
- generalized secrets management through AWS Secrets Manager or another external vault
- automated rotation for non-API-key secrets
- externally immutable audit retention or SIEM export

The API usage path can optionally publish hash-chained JSONL records through `AGENTFLOW_AUDIT_LOG_PATH` in addition to DuckDB analytics. This is useful local evidence that DuckDB analytics are not the only audit path, but object-lock retention, SIEM delivery, and external immutability still need operator evidence outside the repository. Use `docs/operations/immutable-retention-evidence-handoff.md` before making any external immutable-retention claim.

Because the external controls are not provable from the checked-in code, they should not be claimed in customer-facing security questionnaires without additional infrastructure evidence.

Evidence: `src/serving/api/auth/middleware.py`, `src/serving/api/analytics.py`, `docs/runbook.md`

## 10. Known Limitations

The current implementation has several material limitations:

1. No external penetration test evidence is present in the repository.
2. DuckDB encryption is optional and operator-configured; the default file path remains unencrypted for backward compatibility, and DuckDB encryption is not a compliance attestation by itself.
3. Secrets management appears environment- and chart-driven in this snapshot; a managed secret store is not demonstrated.
4. The security pipeline is strong at code scanning and SBOM generation, but a real signed container-release run is still evidence-pending until CI signs a published image digest.
5. The demo-data initialization path is convenient for development, but it increases the importance of strict environment separation between demo and production deployments.
6. Browser-oriented security headers exist, and request body size enforcement is applied from `SecurityPolicy.request_size_limit_bytes`.

## 11. Compliance Readiness

### GDPR

Partial readiness. The repo supports response-time PII masking, tenant scoping, and usage auditing. That helps with least-privilege data exposure and auditability. However, GDPR readiness is incomplete without documented data retention policies, deletion workflows, subject access procedures, and infrastructure evidence for storage/backup handling.

### SOC 2

Partial readiness. Access control, audit logging, CI security scans, and operational runbooks are present. Missing evidence includes change-management controls outside git/CI, vendor management, centralized secrets management, formal incident program artifacts, and third-party audit evidence.

### HIPAA

Not ready based on the reviewed repository. Optional DuckDB at-rest encryption does not supply the broader administrative, contractual, audit-retention, or external-assessment controls HIPAA would require.

## 12. Overall Assessment

For an engineering-led v1 product, AgentFlow shows an above-average application security baseline:
- strong typed validation
- practical tenant isolation
- real SQL safety controls
- concrete key rotation mechanics
- response-time privacy masking
- usable audit trail and CI scanning

The main gap is not the app layer. It is the absence of externally verifiable infrastructure and governance controls. These gaps do not block continued development, package publication, or demos, but they do block enterprise-facing security claims:
- external penetration testing, including report scope, dates, severity summary, remediation map, retest status, and owner
- documented secrets-management architecture
- explicit encryption-at-rest posture for deployment targets
- external immutable retention evidence before claiming WORM/Object Lock/SIEM-backed audit logs
- a short customer-facing security overview aligned to the facts above
