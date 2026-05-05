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

Tenant isolation is not only a naming convention in this codebase. The serving layer includes explicit tenant routing through `TenantRouter`, which maps tenant IDs to Kafka topic prefixes and DuckDB schema names. The SQL builder qualifies known tables with the tenant schema and fails closed when tenant-scoped tables exist but no tenant context is available.

This is stronger than soft application filtering because the query builder rewrites table references before execution. Integration tests show that the same logical order ID can resolve to different rows for different tenants and that cross-tenant lookups return `404` rather than leaking another tenant's data.

The current evidence supports the claim "tenant-scoped DuckDB schemas with fail-closed query resolution." It does not support broader claims such as end-to-end isolation across every external dependency.

Evidence: `src/ingestion/tenant_router.py`, `src/serving/semantic_layer/query/sql_builder.py`, `src/serving/semantic_layer/query/engine.py`, `tests/integration/test_tenant_isolation.py`

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

Evidence: `src/serving/semantic_layer/sql_guard.py`, `src/serving/semantic_layer/query/sql_builder.py`, `tests/unit/test_query_engine_injection.py`, `tests/unit/test_sql_guard.py`

## 6. Rate Limiting and Abuse Protection

Rate limiting exists at two levels:
- per-key request quotas enforced through `RateLimiter`
- per-IP throttling for repeated failed authentication attempts

`RateLimiter` uses Redis when available and falls back to an in-memory sliding window when Redis is unavailable or intentionally disabled. The auth middleware returns `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `Retry-After` headers, so clients can adapt to the policy rather than blindly retrying.

The SDKs also include resilience primitives, specifically retry policy handling and a circuit breaker. This is not a server-side abuse control by itself, but it does reduce retry storms and repeated hammering of degraded endpoints by well-behaved clients.

Evidence: `src/serving/api/rate_limiter.py`, `src/serving/api/auth/middleware.py`, `sdk/agentflow/client.py`, `sdk-ts/src/client.ts`, `tests/unit/test_sdk_circuit_breaker.py`

## 7. Data Protection and Privacy Controls

Response-side PII masking is implemented in `PiiMasker` and applied on entity responses and NL-query results. Masking behavior is configured through `config/pii_fields.yaml`, supports multiple strategies (`partial`, `full`, `hash`), and allows explicit tenant exemptions for internal tenants. When masking is applied, the API sets `X-PII-Masked: true`.

Security headers are applied centrally and include:
- `Strict-Transport-Security`
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Referrer-Policy`

These controls improve baseline browser-facing hardening for docs/admin surfaces. TLS itself is still assumed to be terminated by an upstream edge or ingress layer; that part is not implemented inside the FastAPI application.

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

The API usage path can optionally publish hash-chained JSONL records through `AGENTFLOW_AUDIT_LOG_PATH` in addition to DuckDB analytics. This is useful local evidence that DuckDB analytics are not the only audit path, but object-lock retention, SIEM delivery, and external immutability still need operator evidence outside the repository.

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

The main gap is not the app layer. It is the absence of externally verifiable infrastructure and governance controls. Before a broad enterprise launch, the highest-value next steps are:
- external penetration testing
- documented secrets-management architecture
- explicit encryption-at-rest posture for deployment targets
- a short customer-facing security overview aligned to the facts above
