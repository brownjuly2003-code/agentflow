# API/Auth/Security Audit - AgentFlow

Дата: 2026-04-27  
Scope: `D:\DE_project`, HEAD `4a13d36`  
Фокус: FastAPI auth, permissions, tenant isolation, API control-plane routes.  
Метод: статический code trace по `src/serving/api`, `src/serving/semantic_layer`, `src/processing`; live HTTP-запросы не выполнялись.

## Attack Surface

- Auth middleware: `src/serving/api/auth/middleware.py`
- API key/key rotation: `src/serving/api/auth/manager.py`, `src/serving/api/auth/key_rotation.py`
- Core API: `/v1/query`, `/v1/entity`, `/v1/metrics`, `/v1/batch`, `/v1/search`, `/v1/stream/events`
- Control plane: `/v1/webhooks`, `/v1/alerts`, `/v1/deadletter`, `/v1/lineage`, `/v1/slo`
- Admin: `/v1/admin/*`, `/admin/*`

## Findings Summary

| # | Severity | Confidence | Area | Finding |
|---|---|---:|---|---|
| 1 | CRITICAL | 9/10 | Tenant isolation | Webhook dispatcher can deliver every tenant's pipeline events to every active tenant webhook |
| 2 | CRITICAL | 9/10 | Tenant isolation | Dead-letter API is not tenant-scoped and exposes payloads plus replay/dismiss actions |
| 3 | HIGH | 9/10 | Tenant isolation | Stream/lineage/SLO endpoints read global pipeline events without tenant context |
| 4 | HIGH | 9/10 | Permissions | `allowed_entity_types` is bypassed by NL query, metrics, batch query, and search |
| 5 | HIGH | 8/10 | Auth | Missing/empty API key config fails open for non-admin API routes |
| 6 | HIGH | 8/10 | Permissions | Any tenant API key can mutate webhooks and alerts; no write scopes/roles |
| 7 | MEDIUM | 8/10 | Secret handling | Admin surfaces expose reusable secrets after authentication |

## Finding 1: Tenant Webhooks Receive Global Pipeline Events

**Severity:** CRITICAL  
**Confidence:** 9/10  
**Status:** VERIFIED by code trace  
**Files/lines:** `src/serving/api/webhook_dispatcher.py:199`, `src/serving/api/webhook_dispatcher.py:201`, `src/serving/api/webhook_dispatcher.py:209`, `src/serving/api/webhook_dispatcher.py:302`, `src/serving/api/routers/webhooks.py:29`

**Evidence:** webhook registrations are tenant-tagged at create time, but dispatcher loads all active webhooks and fetches one global `pipeline_events` stream:

- `src/serving/api/routers/webhooks.py:29-35` stores `tenant=_tenant(request)`.
- `src/serving/api/webhook_dispatcher.py:199-211` loads all active webhooks, fetches all pipeline events once, then iterates every event over every webhook.
- `src/serving/api/webhook_dispatcher.py:289-303` reads `SELECT * FROM pipeline_events` with no tenant schema or tenant filter.

**Exploit scenario:** a malicious tenant creates `/v1/webhooks` with no filters. When another tenant produces order/user/session events, `dispatch_new_events()` posts those event bodies to the malicious tenant's URL because `_matches_filters()` only checks event fields, not `webhook.tenant`.

**Impact:** cross-tenant event exfiltration, including any fields present in `pipeline_events`. The webhook signature does not mitigate this; it authenticates the sender to the attacker-controlled receiver.

**Remediation:**
- Add a tenant identifier to pipeline events, or store pipeline events in tenant schemas.
- In `dispatch_new_events()`, deliver only events whose tenant matches `webhook.tenant`.
- If event tenant cannot be determined, fail closed and skip delivery.
- Add regression tests with two tenants and two webhooks proving tenant A never receives tenant B events.

## Finding 2: Dead-Letter API Is Global And Exposes Payloads

**Severity:** CRITICAL  
**Confidence:** 9/10  
**Status:** VERIFIED by code trace  
**Files/lines:** `src/serving/api/routers/deadletter.py:94`, `src/serving/api/routers/deadletter.py:137`, `src/serving/api/routers/deadletter.py:229`, `src/serving/api/routers/deadletter.py:244`, `src/serving/api/routers/deadletter.py:264`, `src/serving/api/routers/deadletter.py:291`

**Evidence:** every dead-letter query reads `dead_letter_events` directly and never filters by tenant:

- stats/list endpoints query all failed events at `deadletter.py:94-204`.
- detail endpoint returns `payload` for any `event_id` at `deadletter.py:229-255`.
- replay/dismiss mutate by `event_id` at `deadletter.py:264-295`.
- `_require_deadletter_write_access()` at `deadletter.py:83-91` checks only whether `allowed_entity_types` is `None`; it does not check tenant ownership.

**Exploit scenario:** tenant A calls `/v1/deadletter` and receives event IDs, failure details, and timestamps for tenant B. Then tenant A calls `/v1/deadletter/{event_id}` and receives the failed event payload. A broad tenant key can also replay or dismiss another tenant's event if it knows the ID.

**Impact:** cross-tenant payload disclosure and potential cross-tenant operational tampering.

**Remediation:**
- Persist `tenant_id` on `dead_letter_events`.
- Apply `WHERE tenant_id = request.state.tenant_id` to stats, list, detail, replay, and dismiss.
- Replace the current `allowed_entity_types is None` write gate with explicit scopes, for example `deadletter:read` and `deadletter:write`.
- Add tests for list/detail/replay/dismiss using two tenants and shared-looking event IDs.

## Finding 3: Stream, Lineage, And SLO Endpoints Ignore Tenant Context

**Severity:** HIGH  
**Confidence:** 9/10  
**Status:** VERIFIED by code trace  
**Files/lines:** `src/serving/api/routers/stream.py:22`, `src/serving/api/routers/stream.py:35`, `src/serving/api/routers/lineage.py:68`, `src/serving/api/routers/lineage.py:87`, `src/serving/api/routers/slo.py:90`, `src/serving/api/routers/slo.py:135`

**Evidence:**
- `/v1/stream/events` reads `pipeline_events` directly from `request.app.state.query_engine._conn`, with no `request.state.tenant_id` use.
- `/v1/lineage/{entity_type}/{entity_id}` fetches matching events by `entity_id` only from global `pipeline_events`.
- `/v1/slo` computes latency/freshness/error-rate over global `pipeline_events`.

**Exploit scenario:** tenant A subscribes to `/v1/stream/events` or queries `/v1/lineage/order/{known_or_guessed_id}` and sees event IDs, entity IDs, topics, timestamps, and latency data from tenant B. `/v1/slo` also discloses aggregate health across all tenants rather than the caller's tenant.

**Impact:** cross-tenant operational metadata disclosure. Depending on event ID/entity ID semantics, this can leak customer activity, volume, failure patterns, and source-system details.

**Remediation:**
- Route these endpoints through `QueryEngine` tenant-aware table qualification instead of direct `query_engine._conn`.
- Add tenant filters to `pipeline_events` queries or use tenant schemas consistently.
- Apply `allowed_entity_types` to `stream` and `lineage` entity filters.
- Add tenant-isolation tests for stream, lineage, and SLO.

## Finding 4: Entity Permissions Are Enforced Only On Direct Entity Reads

**Severity:** HIGH  
**Confidence:** 9/10  
**Status:** VERIFIED by code trace  
**Files/lines:** `src/serving/api/auth/middleware.py:102`, `src/serving/api/routers/agent_query.py:139`, `src/serving/api/routers/agent_query.py:399`, `src/serving/api/routers/batch.py:147`, `src/serving/api/routers/search.py:51`, `src/serving/semantic_layer/query/nl_queries.py:173`

**Evidence:** `allowed_entity_types` is enforced only when `_entity_type_from_path()` matches `/v1/entity/{entity_type}/...`.

- `auth/middleware.py:102-103` checks entity permissions only for direct entity path matches.
- `/v1/query` passes tenant ID to the engine but does not restrict tables by `tenant_key.allowed_entity_types`.
- `nl_queries.py:173-176` allows every catalog table plus `pipeline_events`.
- `/v1/metrics/{metric_name}` does not map metrics to allowed entity/table permissions.
- `/v1/batch` enforces entity restrictions for `type="entity"` but not for `type="query"` or `type="metric"`.
- `/v1/search` accepts caller-supplied `entity_types` but does not intersect them with key permissions.

**Exploit scenario:** a key configured for `allowed_entity_types: ["order"]` is blocked from `GET /v1/entity/user/...`, but can call `POST /v1/query` with "top products", "active sessions", or a user question that the NL layer translates to allowed catalog tables. The same key can use `/v1/search` to discover product/session/user snippets and endpoints.

**Impact:** horizontal permission bypass inside a tenant; entity-scoped keys are not actually scoped across the API surface.

**Remediation:**
- Introduce a central authorization helper that maps route/action to required entity types or scopes.
- In NL-to-SQL, restrict the LLM schema prompt and `allowed_tables` to the caller's allowed entity tables.
- Map metrics to source entity/table permissions before executing.
- Intersect search results and requested `entity_types` with `tenant_key.allowed_entity_types`.
- Add tests for denied query/search/metric/batch-query access using a restricted key.

## Finding 5: API Key Misconfiguration Fails Open

**Severity:** HIGH  
**Confidence:** 8/10  
**Status:** VERIFIED by code trace  
**Files/lines:** `src/serving/api/auth/middleware.py:34`, `src/serving/api/auth/manager.py:330`, `src/serving/api/auth/manager.py:338`, `src/serving/api/main.py:205`

**Evidence:** non-admin auth is skipped when no keys are loaded:

- `auth/middleware.py:34-35` lets every non-admin route through when `not manager.has_configured_keys()`.
- `manager.py:330-338` returns an empty config if the configured key file is missing.
- `main.py:205-209` labels this mode as `open (set config/api_keys.yaml to enable)`.

**Exploit scenario:** a production deployment has a missing Secret mount, empty `api_keys.yaml`, or unset `AGENTFLOW_API_KEYS_FILE`. The API starts and serves `/v1/query`, `/v1/entity`, `/v1/deadletter`, `/v1/webhooks`, and other non-admin routes without API-key authentication.

**Impact:** full unauthenticated access to non-admin API and tenant control-plane routes under a common deployment misconfiguration.

**Remediation:**
- Fail closed by default when not in explicit demo/local mode.
- Require an explicit flag such as `AGENTFLOW_ALLOW_OPEN_AUTH=true` for unauthenticated local development.
- If `AGENTFLOW_API_KEYS_FILE` is set but missing or has zero keys, fail startup.
- Add a deployment smoke test that starts with a missing key file and expects startup failure or `503`, not open API.

## Finding 6: Tenant API Keys Can Mutate Webhooks And Alerts Without Write Scopes

**Severity:** HIGH  
**Confidence:** 8/10  
**Status:** VERIFIED by code trace  
**Files/lines:** `src/serving/api/routers/webhooks.py:29`, `src/serving/api/routers/webhooks.py:46`, `src/serving/api/routers/alerts.py:64`, `src/serving/api/routers/alerts.py:88`, `src/serving/api/routers/alerts.py:106`, `src/serving/api/auth/manager.py:70`

**Evidence:** API keys have `tenant`, `rate_limit_rpm`, and `allowed_entity_types`, but no action scopes or roles. Webhook and alert mutating routes rely only on the global auth middleware:

- `/v1/webhooks` create/delete/test routes do not check write permission.
- `/v1/alerts` create/update/delete/test routes do not check write permission.
- `KeyCreateRequest` has no `scopes`, `role`, or `permissions` field.

**Exploit scenario:** a low-privilege tenant key intended for read-only agent usage can create an outbound webhook or alert pointing to an attacker-controlled URL, or delete/modify existing tenant alerts/webhooks.

**Impact:** privilege escalation within a tenant and a practical exfiltration path when combined with tenant event delivery issues.

**Remediation:**
- Add explicit scopes, for example `entity:read`, `query:read`, `webhook:write`, `alert:write`, `deadletter:write`.
- Enforce scopes via FastAPI dependencies per router/action.
- Treat `allowed_entity_types` as data-scope only, not as write authorization.
- Add tests proving restricted keys cannot create/update/delete webhooks or alerts.

## Finding 7: Admin Surfaces Expose Reusable Secrets

**Severity:** MEDIUM  
**Confidence:** 8/10  
**Status:** VERIFIED by code trace  
**Files/lines:** `src/serving/api/auth/key_rotation.py:35`, `src/serving/api/auth/key_rotation.py:41`, `src/serving/api/routers/admin.py:34`, `src/serving/api/routers/admin_ui.py:50`, `src/serving/api/templates/admin.html:110`, `src/serving/api/templates/admin.html:213`

**Evidence:**
- `list_keys_with_usage()` includes `"key": runtime_key` in the list response when plaintext runtime material exists.
- `/v1/admin/keys` returns that list directly.
- Admin UI reflects `X-Admin-Key` into `data-admin-key` in the HTML body and reads it from JavaScript for refresh requests.

**Exploit scenario:** anyone with admin page access, browser extension access, saved HTML, or debug tooling can recover the admin key from DOM. Anyone with `X-Admin-Key` can call `/v1/admin/keys` and recover active tenant API keys that are cached in process after create/rotate or stored as plaintext legacy keys.

**Impact:** unnecessary long-lived secret exposure after authentication. This increases blast radius of admin UI compromise and makes key rotation less effective.

**Remediation:**
- Return plaintext API keys only once, from create/rotate endpoints.
- Remove `"key"` from `/v1/admin/keys`; return key ID, tenant, name, hash presence, slot state, and usage only.
- Do not embed `X-Admin-Key` into HTML. Use an HttpOnly, Secure, SameSite admin session cookie or require explicit header-based API usage outside the rendered page.
- Add tests asserting `/v1/admin/keys` never returns active key material.

## Controls That Look Sound In This Scope

- Direct `/v1/entity/{entity_type}/{entity_id}` reads pass tenant ID into `QueryEngine` and use tenant-aware table qualification.
- Metric reads pass tenant ID and cache keys include tenant.
- Admin routes use `Depends(require_admin_key)` and are skipped by normal API-key middleware rather than exposed without their own dependency.
- API key hashes use bcrypt by default with configured rounds.

## Test Gaps To Add

- Two-tenant webhook dispatch test: tenant B event must not hit tenant A webhook.
- Two-tenant dead-letter list/detail/replay/dismiss tests.
- Stream, lineage, and SLO tests with tenant-specific pipeline events.
- Restricted-key tests for `/v1/query`, `/v1/query/explain`, `/v1/metrics/*`, `/v1/batch`, and `/v1/search`.
- Misconfigured auth startup test for missing/empty key config outside explicit demo/open mode.
- Scope tests for webhook/alert write operations.
